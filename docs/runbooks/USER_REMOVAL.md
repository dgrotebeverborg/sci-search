# User access removal runbook

Sci-Search identifies a federated user by `(issuer, subject)`, never by email. Confirm that pair and the internal user ID before changing access.

1. Disable or remove the user's project and workspace memberships in one audited administrative transaction. Transfer ownership first when the user is the only owner.
2. Revoke every active server-side session for the internal user ID.
3. If required by institutional policy, disable the identity upstream; Sci-Search must still deny the revoked memberships if the identity later authenticates again.
4. Verify the user receives the same not-found response for former project identifiers as any unrelated user.
5. Retain audit records according to policy. Profile fields such as email may be minimized separately, but `(issuer, subject)` and scientific-review authorship must not be silently reassigned.
6. Do not delete shared content-addressed documents solely because one grant is removed. Revoke that project's grant; storage cleanup occurs only when no live grant, run, artifact, retention rule, or legal hold references the blob.

Emergency removal follows the compromised-session procedure in [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md). Record the operator, target internal ID, affected scopes, session count revoked, ownership transfers, and verification result without copying research content.

