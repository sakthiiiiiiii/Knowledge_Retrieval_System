"""Permission-filtered retrieval, cloud synthesis or explicit source excerpts, citations."""

import time
import re
from .cache import cache_key, valid_cached
from .generation import (
    ABSTAIN,
    validate_answer,
    GenerationError,
    ExtractiveGenerator,
    unsupported_question,
)
from .security import allowed
from .lexical import terms


class AnswerEngine:
    def __init__(self, settings, registry, store, embedder, generator, cache=None):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.embedder = embedder
        self.generator = generator
        self.cache = cache

    def ask(self, question, principal, namespace="hr", history=None):
        # Step 1: Validate the request before spending time on retrieval or
        # generation.
        start = time.perf_counter()
        question = question.strip()
        if not question or len(question) > 1500:
            raise ValueError("Question must be 1–1500 characters")
        if namespace not in {"hr", "operations", "research"}:
            raise ValueError("Unknown knowledge area")
        history = (history or [])[-4:]

        def result(answer, status, sources=None, **extra):
            return {
                "answer": answer,
                "status": status,
                "sources": sources or [],
                "cached": False,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                **extra,
            }

        # Reject live-balance and unrelated general questions because this corpus
        # cannot substantiate them.
        if unsupported_question(question):
            return result(ABSTAIN, "no_evidence")

        # Step 2: Tie cached answers to the user, permissions, settings and current
        # corpus version.
        key = cache_key(
            principal,
            namespace,
            question,
            history,
            self.settings,
            self.registry.epoch(),
        )
        if self.cache:
            cached = self.cache.get(key)
            if cached and valid_cached(cached, principal, self.store):
                return {
                    **cached["result"],
                    "cached": True,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                }

        # Step 3: Restore a little context for short leave follow-ups such as "sick?".
        search_question = question
        if history and len(terms(question)) < 4 and "leave" in terms(history[-1]):
            if set(terms(question)) & {
                "annual",
                "sick",
                "casual",
                "maternity",
                "paternity",
                "bereavement",
            }:
                search_question += " leave"

        # Retrieve evidence through the selected backend with the user's access
        # restrictions.
        vector = self.embedder.encode_query(search_question)
        hits = self.store.search(
            vector,
            principal,
            namespace,
            self.settings.top_candidates,
            self.settings.min_score,
            self.settings.retrieval_id,
        )
        if "leave" in terms(search_question):
            # Preserve the source's eligibility and crediting qualifications alongside
            # entitlement rows.
            supplements = self.store.search(
                self.embedder.encode_query(
                    "scope contractors interns proportion months remaining"
                ),
                principal,
                namespace,
                6,
                0,
                self.settings.retrieval_id,
            )
            scope = [
                p
                for _, p in supplements
                if p["source_group"] == "D03"
                and (
                    p["heading"].startswith("3. Scope")
                    or (
                        "4.1 Leave entitlement" in p["heading"]
                        and not p["text"].startswith("Leave type:")
                    )
                )
            ]
            generic = not (
                set(terms(search_question))
                & {"annual", "sick", "casual", "maternity", "paternity", "bereavement"}
            )
            if generic:
                hits.sort(
                    key=lambda x: (
                        not x[1]["text"].startswith("Leave type:"),
                        (
                            int(re.search(r"row (\d+)", x[1]["locator"]).group(1))
                            if x[1]["text"].startswith("Leave type:")
                            else -x[0]
                        ),
                    )
                )
        else:
            scope = []

        # Step 4: Remove duplicate evidence so repeated passages do not crowd out
        # useful context.
        chosen = []
        seen = set()
        for _, p in hits:
            if not allowed(principal, p) or not p.get("active"):
                continue
            fingerprint = (
                p.get("source_group", p["document_id"]),
                p["heading"],
                p["text"],
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            chosen.append(p)
            if len(chosen) >= self.settings.top_k - min(
                len(scope), self.settings.top_k - 1
            ):
                break
        for p in scope:
            if (
                p["chunk_id"] not in {c["chunk_id"] for c in chosen}
                and len(chosen) < self.settings.top_k
            ):
                chosen.append(p)
        if not chosen:
            return result(ABSTAIN, "no_evidence")

        # Step 5: Apply the cloud disclosure policy before sending any retrieved
        # passage to Groq.
        external = getattr(self.generator, "external", True)
        if external and not self.settings.allow_external_confidential:
            chosen = [
                p
                for p in chosen
                if p["classification"] in ("internal", "research-approved")
            ]
            if not chosen:
                return result(
                    (
                        "This question needs restricted documents that cannot be sent to the "
                        "cloud under the current policy."
                    ),
                    "cloud_privacy_blocked",
                )
        if not all(allowed(principal, p) and p.get("active") for p in chosen):
            raise PermissionError("Access changed during retrieval")

        # Step 6: Validate generated citations; on a provider failure, show honest
        # source excerpts.
        warning, code = None, None
        local = not external
        try:
            checked = validate_answer(
                self.generator.generate(search_question, chosen, history), chosen
            )
        except GenerationError as exc:
            warning, code = str(exc), exc.code
            checked = validate_answer(
                ExtractiveGenerator().generate(search_question, chosen, history), chosen
            )
            local = True
        if checked["status"] == "invalid_citations" and external:
            warning = (
                "The generated answer could not be verified. "
                "Showing source excerpts instead."
            )
            code = "invalid_citations"
            checked = validate_answer(
                ExtractiveGenerator().generate(search_question, chosen, history), chosen
            )
            local = True

        # Step 7: Attach source locations so the user can inspect the exact passages
        # behind the answer.
        cited = []
        for cid in checked["ids"]:
            p = chosen[int(cid[1:]) - 1]
            cited.append(
                {
                    "citation": cid,
                    "source_filename": p["source_filename"],
                    "locator": p["locator"],
                    "heading": p["heading"],
                    "document_id": p["document_id"],
                    "chunk_id": p["chunk_id"],
                    "version": p["version"],
                    "excerpt": p["text"],
                }
            )
        status = (
            "source_excerpts"
            if local and checked["status"] == "answered"
            else checked["status"]
        )
        output = result(
            checked["answer"],
            status,
            cited,
            answer_mode="source_excerpts" if local else "groq",
        )
        if warning:
            output.update(warning=warning, error_code=code)

        # Cache successful internal answers only; do not persist provider-failure
        # fallbacks or restricted text.
        if (
            self.cache
            and not warning
            and status in {"answered", "source_excerpts"}
            and all(p["classification"] == "internal" for p in chosen)
        ):
            ttl = 300 if namespace == "operations" else 3600
            self.cache.set(
                key,
                {
                    "result": {k: v for k, v in output.items() if k != "latency_ms"},
                    "chunk_ids": [p["chunk_id"] for p in chosen],
                },
                ttl,
            )
        return output
