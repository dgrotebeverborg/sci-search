import {request} from './api.js';
import {element, fields} from './dashboard.js';

export async function submitArticleFeedback({projectId, runId, publicationId, decision, reason, expectedSequence, reviewedRevision, idempotencyKey}) {
  return request(`/api/v1/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/articles/${encodeURIComponent(publicationId)}/feedback`, {
    method: 'POST', body: {decision, ...(reason?.trim() ? {reason: reason.trim()} : {}), expected_sequence: expectedSequence, reviewed_revision: reviewedRevision, idempotency_key: idempotencyKey || crypto.randomUUID()},
  });
}
export function articleControls(study, snapshot, context) {
  const root = element('div', '', 'article-feedback');
  const effective = snapshot.effective_decisions?.[study.publication_id];
  if (effective) fields({researcher_decision: effective}, root);
  const allowed = ['owner', 'reviewer'].includes(snapshot.role || context.role) && !context.historical && snapshot.rebuild_available !== false;
  const buttons = element('div', '', 'button-row'); root.append(buttons);
  const form = element('form'); form.hidden = true;
  const heading = element('p');
  const reasonLabel = element('label', 'Reason');
  const reason = element('textarea'); reason.rows = 2; reason.maxLength = 1000;
  reason.id = `reason-${encodeURIComponent(study.publication_id)}`; reasonLabel.htmlFor = reason.id;
  reason.placeholder = 'Why is this article relevant or irrelevant to this question?';
  const save = element('button', 'Save decision', 'button button-primary'); save.type = 'submit';
  const cancel = element('button', 'Cancel decision', 'button button-quiet'); cancel.type = 'button'; cancel.onclick = () => { form.hidden = true; };
  const status = element('p', '', 'status'); status.setAttribute('role', 'status');
  form.append(heading, reasonLabel, reason, save, cancel, status); root.append(form);
  let decision = null, idempotencyKey = null;
  for (const [value, title] of [['include', 'Include article'], ['exclude', 'Exclude article'], ['background', 'Use as background'], ['reset', 'Reset article decision']]) {
    const button = element('button', title, 'button button-secondary'); button.type = 'button'; button.disabled = !allowed;
    button.onclick = () => { decision = value; idempotencyKey = crypto.randomUUID(); heading.textContent = title; form.hidden = false; reason.focus(); };
    buttons.append(button);
  }
  if (!allowed) root.append(element('p', snapshot.rebuild_available === false ? 'The retained source ledger is unavailable. This recovered dashboard can be read but cannot be rebuilt.' : context.historical ? 'Historical revision: open the current revision to change relevance.' : 'Article decisions require an owner or reviewer role.', 'help'));
  form.onsubmit = async (event) => {
    event.preventDefault(); save.disabled = true;
    try {
      const receipt = await submitArticleFeedback({projectId: context.projectId, runId: snapshot.run_id, publicationId: study.publication_id, decision, reason: reason.value, expectedSequence: snapshot.feedback_sequence || 0, reviewedRevision: snapshot.revision, idempotencyKey});
      status.textContent = `${decision} decision saved. Updating dashboard…`;
      await context.onFeedback?.(receipt);
    } catch (error) {
      status.textContent = error.status === 409 ? 'Another decision was saved. Reload the current revision before trying again.' : error.message;
      save.disabled = false;
    }
  };
  return root;
}
