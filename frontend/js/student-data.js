import { requestJSON } from './api.js';

export function createStudentData() {
  const panel = document.getElementById('data-panel');
  const toggleButton = document.getElementById('data-toggle');
  const list = document.getElementById('data-list');
  const status = document.getElementById('data-status');
  let controller = new AbortController();

  function setStatus(message = '', error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
  }

  const request = (path, method = 'GET', body) => requestJSON(path, {
    method, body, signal: controller.signal,
  });

  function showSection(title, rows, kind, label) {
    const heading = document.createElement('p');
    heading.textContent = title;
    list.appendChild(heading);
    if (!rows.length) {
      const empty = document.createElement('p');
      empty.textContent = '暂无';
      list.appendChild(empty);
    }
    for (const row of rows) {
      const line = document.createElement('div');
      line.className = 'row';
      const value = document.createElement('span');
      value.style.flex = '1';
      value.textContent = label(row);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '删除';
      remove.addEventListener('click', () => mutate(
        () => request('/api/me/' + kind + '/' + encodeURIComponent(row.course_id), 'DELETE'),
        '已删除 ' + row.course_id));
      line.append(value, remove);
      list.appendChild(line);
    }
  }

  async function refresh() {
    const current = controller;
    try {
      const [courses, grades] = await Promise.all([
        request('/api/me/courses'), request('/api/me/grades'),
      ]);
      if (controller !== current) return;
      list.replaceChildren();
      showSection('已选课程', courses.courses, 'courses', row => row.course_id + ' ' + row.name);
      showSection('已录成绩', grades.grades, 'grades', row => row.course_id + ' ' + row.letter + ' (' + row.grade_point + ')');
    } catch (error) {
      if (controller === current && error.name !== 'AbortError') setStatus(error.message, true);
    }
  }

  function toggle() {
    const open = panel.classList.toggle('open');
    panel.setAttribute('aria-hidden', String(!open));
    toggleButton.setAttribute('aria-expanded', String(open));
    if (open) { refresh(); panel.querySelector('button').focus(); }
    else toggleButton.focus();
  }

  async function mutate(operation, success) {
    const current = controller;
    try {
      await operation();
      if (controller !== current) return;
      setStatus(success);
      await refresh();
    } catch (error) {
      if (controller === current && error.name !== 'AbortError') setStatus(error.message, true);
    }
  }

  function saveCourse() {
    return mutate(() => request('/api/me/courses', 'PUT', {
      course_id: document.getElementById('course-id').value.trim(),
    }), '课程已保存');
  }

  function saveGrade() {
    return mutate(() => {
      const point = document.getElementById('grade-point').value;
      const letter = document.getElementById('grade-letter').value.trim();
      if (!point || !letter) throw new Error('请填写绩点和等级');
      return request('/api/me/grades', 'PUT', {
        course_id: document.getElementById('grade-course').value.trim(),
        grade_point: Number(point), letter,
      });
    }, '成绩已保存');
  }

  function reset() {
    controller.abort();
    controller = new AbortController();
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    toggleButton.setAttribute('aria-expanded', 'false');
    list.replaceChildren();
    setStatus();
    panel.querySelectorAll('input').forEach(input => { input.value = ''; });
  }

  return { toggle, saveCourse, saveGrade, reset, isOpen: () => panel.classList.contains('open') };
}
