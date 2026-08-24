# X automation fixed rules (reviewed 2026-08-24)

Phase 7 is read-only. The X adapter may resolve users, read mentions, and look up posts. It has no method for posting, replying, liking, reposting, following, messaging, deleting, hiding replies, or editing profiles.

Future automated replies must follow X's current Automation Rules:

- Do not send unsolicited automated replies or use keyword matching alone as consent.
- A user's direct reply or a mention that clearly requests contact may indicate intent; following alone does not.
- Provide and promptly honor opt-out.
- At most one automated reply per user interaction.
- Check that the source post still exists before any future reply.
- AI-powered automated reply bots require X's prior explicit written approval.

Until that approval exists, `X_WRITE_ENABLED`, `ALLOW_AUTOMATED_REPLIES`, and every external-send gate remain false. Reply candidates stop at human review and cannot transition to `sent`.

Sources: X Automation Rules and X API v2 documentation, checked on the date above.
