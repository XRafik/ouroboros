"""Native review's image staging and delivery facts; no loader or image store.

The registered view_image uses the common vision loader on a private context,
as the mind's tool-round auto-attachment does. Only a returned call is adopted;
pixels join the conversation after every tool reply. Route projections keep
the original, and delivery is observed separately from attaching a local file.
"""
from __future__ import annotations

import base64
import copy
import hashlib

from ouroboros.vision_routing import _image_url_from_block, _is_image, _rewrite


def staged_image_registry(registry):
    private = copy.copy(registry)
    private._ctx = copy.copy(registry._ctx)
    private._ctx.messages = []  # A late worker owns only this sink, never the live transcript.
    return private


def _blocks(messages):
    for message in messages:
        if isinstance(message.get("content"), list):
            yield from (part for part in message["content"] if _is_image(part))


class NativeReviewImages:
    def __init__(self):
        self.pending = []
        self.facts = {}
        self.sent_messages = []
        self.candidates = {}
        self.refusals = {}

    def accept(self, call_id, path, result, private, *, round_idx):
        """Called only by the episode thread, after success OR abandonment."""
        staged = private._ctx.messages if private is not None else []
        blocks = list(_blocks(staged))
        image_id = f"{round_idx}:{call_id}"
        fact = {"image_id": image_id, "call_id": call_id, "round": round_idx, "requested_path": path,
                "status": "staged" if blocks else "unavailable", "delivered": False}
        self.facts[image_id] = fact
        if not blocks:
            fact["reason"] = result
            return result, fact
        for block in blocks:
            block["_review_image_id"] = image_id
            fact.update(source_path=block["_source_path"], source_sha256=block["_source_sha256"])
        self.pending.extend(staged)
        return (f"Image staged for the next request, after all tool replies. Original: {fact['source_path']}. "
                "Attachment alone is not visual inspection; delivery depends on the receiving route."), fact

    def append_after_tools(self, messages, ctx):
        from ouroboros.loop_messages import _append_or_merge_user_content

        start = len(messages)
        for message in self.pending:
            _append_or_merge_user_content(messages, message["content"], stamp=ctx)
        self.pending.clear()
        return messages[start:]

    def prepare(self, messages, slot):
        from ouroboros.vision_image_limits import prepare_route_images
        from ouroboros.vision_routing import _image_input_verdict, _metadata_says_no, own_lane_without_images

        originals = list(_blocks(messages))
        reason = ""
        if originals:
            reason = own_lane_without_images(slot.model, use_local=bool(slot.use_local))
            if not reason and _image_input_verdict(slot.model, model_role=f"reviewer:{slot.slot_id}",
                                                  model_account_override=slot.session_profile) is False:
                reason = _metadata_says_no(slot.model)
        gaps = {}

        def omit(block):
            call_id = block.get("_review_image_id")
            gap = reason or self.refusals.get((call_id, slot.model, slot.session_profile))
            if gap:
                gaps[call_id] = gap
                return f"[Image not delivered: {gap}. No visual inspection. Original: {block.get('_source_path', '')}]"
            return None

        projected = prepare_route_images(_rewrite(messages, omit), slot.model)
        self.candidates = {}
        for block in _blocks(projected):
            call_id = block.get("_review_image_id")
            if call_id not in self.facts:
                continue
            url = _image_url_from_block(block)
            raw = base64.b64decode(url.split(";base64,", 1)[1], validate=True)
            self.candidates[call_id] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                                        "mime": url[5:].split(";", 1)[0], "model": slot.model,
                                        "profile": slot.session_profile}
        present = {block.get("_review_image_id") for block in originals}
        for call_id, fact in self.facts.items():
            if call_id in self.candidates:
                continue
            if call_id in present and call_id not in gaps:
                # The existing route image preparer names format/representation failures.
                notes = [part.get("text", "") for message in projected
                         if isinstance(message.get("content"), list) for part in message["content"]
                         if part.get("type") == "text" and fact.get("source_path", "\0") in part.get("text", "")]
                gaps[call_id] = " ".join(notes) or "image representation unavailable on the receiving route"
            elif fact["status"] == "staged" and call_id not in present:
                gaps[call_id] = "image left the working view before delivery (eviction or authored compaction)"
            if call_id in gaps:
                fact.update(status="unavailable", delivered=False, reason=gaps[call_id])
        # The tool's text must name a route gap too; a local attachment is not delivery.
        if gaps:
            projected = [{**message, "content": f"Image not delivered: {gaps[message['_review_image_id']]}. "
                          f"No visual inspection. Original: {self.facts[message['_review_image_id']].get('source_path', '')}"}
                         if message.get("role") == "tool" and message.get("_review_image_id") in gaps else message
                         for message in projected]
        self.sent_messages = projected
        return projected

    def observe(self, round_idx, *, confirmed=True):
        for call_id, candidate in self.candidates.items():
            fact = self.facts[call_id]
            if confirmed:
                fact.update(status="delivered", delivered=True)
                fact.pop("reason", None)
                fact.setdefault("deliveries", []).append({"round": round_idx, **candidate})
            else:
                fact.update(status="unconfirmed", delivered=False,
                            reason="request dispatched without a successful response; visual inspection unconfirmed")

    def refuse_send(self, error, slot, round_idx, serialized_chars):
        """Existing typed provider facts, never estimates or error-text matching."""
        from ouroboros.llm_attempt import _is_structured_context_overflow_exception
        from ouroboros.vision_routing import completed_image_refusal

        if not self.candidates:
            return False
        if _is_structured_context_overflow_exception(error):
            reason = "provider context window refused the request containing this image; original retained"
        elif refusal := completed_image_refusal(error):
            reason = f"provider refused the request containing this image: {refusal}; original retained"
        else:
            return False
        for image_id, candidate in self.candidates.items():
            self.refusals[(image_id, slot.model, slot.session_profile)] = reason
            fact = self.facts[image_id]
            fact.update(status="unavailable", delivered=False, reason=reason)
            fact.setdefault("refused_requests", []).append({"round": round_idx, **candidate,
                                                            "serialized_chars": serialized_chars, "reason": reason})
        return True
