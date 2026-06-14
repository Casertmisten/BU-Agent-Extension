import { describe, it, expect, beforeEach } from 'vitest';
import '../public/content/content.js';

const {
  tagElements, clearTags, get_element_info,
  clickElement, inputText, scrollPage,
  enableOverlay, disableOverlay,
} = window.__BU_AGENT__;

describe('tagElements', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('为可交互元素打上 backend-id 标签', () => {
    document.body.innerHTML = `
      <button>Submit</button>
      <a href="#">Link</a>
      <input type="text" placeholder="Search">
    `;
    const elements = tagElements();
    expect(elements.length).toBe(3);
    expect(elements[0]).toEqual({ id: 'agent-00', tag: 'button', text: 'Submit', type: '', placeholder: '' });
    expect(elements[1]).toEqual({ id: 'agent-01', tag: 'a', text: 'Link', type: '', placeholder: '' });
    expect(elements[2]).toEqual({ id: 'agent-02', tag: 'input', text: '', type: 'text', placeholder: 'Search' });
  });

  it('重新打标前先移除旧标签', () => {
    document.body.innerHTML = '<button>Old</button>';
    tagElements();
    document.body.innerHTML = '<button>A</button><button>B</button>';
    const elements = tagElements();
    expect(elements.length).toBe(2);
    expect(document.querySelectorAll('[backend-id]').length).toBe(2);
  });

  it('无可交互元素时返回空数组', () => {
    document.body.innerHTML = '<p>Just text</p>';
    expect(tagElements()).toEqual([]);
  });
});

describe('get_element_info', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('返回元素详情', () => {
    document.body.innerHTML = '<input type="email" placeholder="Enter email" value="test@example.com">';
    tagElements();
    const info = get_element_info('agent-00');
    expect(info.tag).toBe('input');
    expect(info.type).toBe('email');
    expect(info.placeholder).toBe('Enter email');
    expect(info.value).toBe('test@example.com');
    expect(info.visible).toBe(true);
  });

  it('未知 id 返回 null', () => {
    expect(get_element_info('agent-99')).toBeNull();
  });
});

describe('clickElement', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('点击目标元素', () => {
    let clicked = false;
    document.body.innerHTML = '<button>Click me</button>';
    tagElements();
    document.querySelector('[backend-id="agent-00"]').addEventListener('click', () => { clicked = true; });
    const result = clickElement('agent-00');
    expect(clicked).toBe(true);
    expect(result.success).toBe(true);
  });

  it('元素不存在时返回错误', () => {
    const result = clickElement('agent-99');
    expect(result.success).toBe(false);
    expect(result.error).toContain('not found');
  });
});

describe('inputText', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('向输入框输入文本', () => {
    document.body.innerHTML = '<input type="text" value="old">';
    tagElements();
    const result = inputText('agent-00', 'new text', true);
    expect(result.success).toBe(true);
    expect(document.querySelector('input').value).toBe('new text');
  });

  it('clear_first 为 false 时追加文本', () => {
    document.body.innerHTML = '<input type="text" value="old">';
    tagElements();
    inputText('agent-00', ' new', false);
    expect(document.querySelector('input').value).toBe('old new');
  });
});

describe('scrollPage', () => {
  it('返回成功', () => {
    expect(scrollPage('down', 300).success).toBe(true);
  });
});

describe('overlay', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('创建遮罩层元素', () => {
    enableOverlay();
    const overlay = document.getElementById('__agent_overlay__');
    expect(overlay).not.toBeNull();
    expect(overlay.style.zIndex).toBe('999999');
    disableOverlay();
  });

  it('禁用时移除遮罩层', () => {
    enableOverlay();
    expect(document.getElementById('__agent_overlay__')).not.toBeNull();
    disableOverlay();
    expect(document.getElementById('__agent_overlay__')).toBeNull();
  });

  it('不会重复创建遮罩层', () => {
    enableOverlay();
    enableOverlay();
    expect(document.querySelectorAll('#__agent_overlay__').length).toBe(1);
    disableOverlay();
  });
});
