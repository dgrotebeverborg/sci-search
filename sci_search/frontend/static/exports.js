export function showExports(project, exports = []) {
  const target = document.getElementById('export-actions');
  target.replaceChildren();
  if (!project || !exports.length) {
    const note = document.createElement('span');
    note.className = 'help';
    note.textContent = 'Downloads become available after a review.';
    target.append(note);
    return;
  }
  for (const item of exports) {
    const link = document.createElement('a');
    link.className = item.primary ? 'button button-primary' : 'button button-secondary';
    link.href = `/api/v1/projects/${project.id}/exports/${item.id}`;
    link.textContent = item.label;
    target.append(link);
  }
}
