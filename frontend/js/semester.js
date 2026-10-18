import { requestJSON } from './api.js';
import { getUser } from './session.js';

let selected = '', terms = [], generation = 0, controller, locked = true;
const selector = () => document.getElementById('semester-select');
const key = () => 'cc_semester:' + getUser();

export const getSemesterId = () => selected || null;

function render() {
  selector().value = selected;
  selector().disabled = locked || !terms.length;
  const term = terms.find(t => t.semester_id === selected);
  const label = document.getElementById('data-semester');
  label.textContent = term ? `${term.label} · 数据版本 ${term.version}` + (term.is_current ? '' : ' · 非当前日期范围')
    : terms.length ? '请选择学期；当前日期没有唯一默认范围。' : '尚未录入学期';
}

export function selectSemester(id, { notify = true } = {}) {
  if (!terms.some(t => t.semester_id === id)) return false;
  const changed = selected !== id;
  selected = id;
  sessionStorage.setItem(key(), selected);
  render();
  if (notify && changed) window.dispatchEvent(new CustomEvent('semesterchange', { detail: selected }));
  return true;
}

export function lockSemester(value) { locked = value; render(); }

export async function loadSemesters() {
  const version = ++generation;
  controller?.abort();
  controller = new AbortController();
  locked = true;
  selector().disabled = true;
  const data = await requestJSON('/api/semesters', { signal: controller.signal });
  if (version !== generation) return;
  terms = data.semesters;
  selector().replaceChildren();
  for (const term of terms) {
    const option = document.createElement('option');
    option.value = term.semester_id;
    option.textContent = term.label;
    selector().append(option);
  }
  selected = terms.some(t => t.semester_id === sessionStorage.getItem(key())) ? sessionStorage.getItem(key()) : data.default_id || '';
  if (!selected) {
    const option = document.createElement('option');
    option.textContent = terms.length ? '请选择学期' : '尚未录入学期';
    option.value = '';
    selector().append(option);
  }
  if (selected) sessionStorage.setItem(key(), selected);
  render();
}

export function resetSemesters() {
  generation++;
  controller?.abort();
  terms = [];
  selected = '';
  locked = true;
  selector().replaceChildren();
  render();
}

selector().addEventListener('change', () => selectSemester(selector().value));
