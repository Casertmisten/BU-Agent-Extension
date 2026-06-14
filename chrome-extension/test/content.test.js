import { describe, it, expect, beforeEach } from 'vitest';
import '../public/content/content.js';
import {
  inferRole, computeName, isHidden, isInteractive,
} from '../public/content/ax-helpers.js';

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

describe('AX inference', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  describe('inferRole', () => {
    it('显式 role 属性优先', () => {
      document.body.innerHTML = '<div role="navigation"></div>';
      expect(inferRole(document.body.firstChild)).toBe('navigation');
    });
    it('HTML 语义标签映射', () => {
      document.body.innerHTML = '<button>x</button><a href="#">y</a><h1>t</h1>';
      expect(inferRole(document.body.children[0])).toBe('button');
      expect(inferRole(document.body.children[1])).toBe('link');
      expect(inferRole(document.body.children[2])).toBe('heading');
    });
    it('input 按 type 映射', () => {
      document.body.innerHTML = '<input type="email"><input type="checkbox">';
      expect(inferRole(document.body.children[0])).toBe('textbox');
      expect(inferRole(document.body.children[1])).toBe('checkbox');
    });
    it('无语义容器返回 null', () => {
      document.body.innerHTML = '<div></div><span></span>';
      expect(inferRole(document.body.children[0])).toBeNull();
      expect(inferRole(document.body.children[1])).toBeNull();
    });
    it('body 推断为 WebArea', () => {
      document.title = 'Test';
      expect(inferRole(document.body)).toBe('WebArea');
    });
    it('a 无 href 返回 null', () => {
      document.body.innerHTML = '<a>no link</a>';
      expect(inferRole(document.body.firstChild)).toBeNull();
    });
  });

  describe('computeName', () => {
    it('aria-label 优先', () => {
      document.body.innerHTML = '<button aria-label="提交">Submit</button>';
      expect(computeName(document.body.firstChild)).toBe('提交');
    });
    it('label for 关联表单字段', () => {
      document.body.innerHTML = '<label for="e">邮箱</label><input id="e" type="email">';
      expect(computeName(document.body.children[1])).toBe('邮箱');
    });
    it('包裹式 label', () => {
      document.body.innerHTML = '<label>搜索<input type="text"></label>';
      const input = document.querySelector('input');
      expect(computeName(input)).toBe('搜索');
    });
    it('textContent 兜底', () => {
      document.body.innerHTML = '<h1>用户登录</h1>';
      expect(computeName(document.body.firstChild)).toBe('用户登录');
    });
    it('placeholder 兜底', () => {
      document.body.innerHTML = '<input type="text" placeholder="请输入">';
      expect(computeName(document.body.firstChild)).toBe('请输入');
    });
    it('长文本截断到 200 字', () => {
      const long = 'a'.repeat(300);
      document.body.innerHTML = `<h1>${long}</h1>`;
      expect(computeName(document.body.firstChild).length).toBe(200);
    });
    it('无任何来源返回空串', () => {
      document.body.innerHTML = '<input type="text">';
      expect(computeName(document.body.firstChild)).toBe('');
    });
  });

  describe('isHidden', () => {
    it('hidden 属性', () => {
      document.body.innerHTML = '<div hidden></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('aria-hidden', () => {
      document.body.innerHTML = '<div aria-hidden="true"></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('display:none', () => {
      document.body.innerHTML = '<div style="display:none"></div>';
      expect(isHidden(document.body.firstChild)).toBe(true);
    });
    it('可见元素返回 false', () => {
      document.body.innerHTML = '<div>可见</div>';
      expect(isHidden(document.body.firstChild)).toBe(false);
    });
  });

  describe('isInteractive', () => {
    it('可交互 role 返回 true', () => {
      expect(isInteractive('button')).toBe(true);
      expect(isInteractive('link')).toBe(true);
      expect(isInteractive('textbox')).toBe(true);
    });
    it('非可交互 role 返回 false', () => {
      expect(isInteractive('heading')).toBe(false);
      expect(isInteractive('main')).toBe(false);
    });
  });
});
