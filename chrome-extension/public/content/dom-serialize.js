// DOM 树脱水序列化层（移植自 dom-tree-migration/dom/index.ts + getPageInfo.ts）
// 提供：提取扁平树 → 序列化为 LLM 文本 → 索引映射 → 页面信息采集
// 通过 window.__DOM_SERIALIZE__ 暴露，供 content.js 调用

;(function () {
  'use strict'

  // 全页模式默认值，-1 表示不裁剪视口、跳过遮挡检测（最昂贵的操作）
  var DEFAULT_VIEWPORT_EXPANSION = -1

  // 语义标签：脱水时即使不可交互也保留，为 LLM 提供上下文
  var SEMANTIC_TAGS = { nav: 1, menu: 1, header: 1, footer: 1, aside: 1, dialog: 1 }

  // 追踪可交互元素是否是新出现的（WeakMap，页面卸载后自动回收）
  var newElementsCache = new WeakMap()

  // === 默认保留的属性列表 ===
  var DEFAULT_INCLUDE_ATTRIBUTES = [
    'title', 'type', 'checked', 'name', 'role', 'value', 'placeholder',
    'data-date-format', 'alt', 'aria-label', 'aria-expanded', 'data-state',
    'aria-checked',
    'id', 'for',
    'target',
    'aria-haspopup', 'aria-controls', 'aria-owns',
    'contenteditable',
  ]

  // === glob 通配符缓存 ===
  var globRegexCache = {}

  function globToRegex(pattern) {
    var regex = globRegexCache[pattern]
    if (!regex) {
      var escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')
      regex = new RegExp('^' + escaped.replace(/\*/g, '.*') + '$')
      globRegexCache[pattern] = regex
    }
    return regex
  }

  function matchAttributes(attrs, patterns) {
    var result = {}
    for (var i = 0; i < patterns.length; i++) {
      var pattern = patterns[i]
      if (pattern.indexOf('*') !== -1) {
        var regex = globToRegex(pattern)
        for (var key in attrs) {
          if (regex.test(key) && attrs[key].trim()) {
            result[key] = attrs[key].trim()
          }
        }
      } else {
        var value = attrs[pattern]
        if (value && value.trim()) {
          result[pattern] = value.trim()
        }
      }
    }
    return result
  }

  /**
   * 调用引擎提取扁平 DOM 树，并标记新出现的可交互元素
   */
  function getFlatTree(config) {
    config = config || {}
    var viewportExpansion = config.viewportExpansion !== undefined
      ? config.viewportExpansion
      : DEFAULT_VIEWPORT_EXPANSION

    var elements = window.__DOM_TREE_ENGINE__({
      doHighlightElements: false,
      debugMode: false,
      focusHighlightIndex: -1,
      viewportExpansion: viewportExpansion,
      interactiveBlacklist: config.interactiveBlacklist || [],
      interactiveWhitelist: config.interactiveWhitelist || [],
      highlightOpacity: 0.0,
      highlightLabelOpacity: 0.1,
    })

    var currentUrl = window.location.href
    for (var nodeId in elements.map) {
      var node = elements.map[nodeId]
      if (node.isInteractive && node.ref) {
        if (!newElementsCache.has(node.ref)) {
          newElementsCache.set(node.ref, currentUrl)
          node.isNew = true
        }
      }
    }
    return elements
  }

  function capTextLength(text, maxLength) {
    if (text.length > maxLength) {
      return text.substring(0, maxLength) + '...'
    }
    return text
  }

  /**
   * 从扁平 map 重建树形结构
   */
  function buildTreeNode(flatTree, nodeId) {
    var node = flatTree.map[nodeId]
    if (!node) return null

    if (node.type === 'TEXT_NODE') {
      return {
        type: 'text',
        text: node.text,
        isVisible: node.isVisible,
        parent: null,
        children: [],
      }
    } else {
      var children = []
      if (node.children) {
        for (var i = 0; i < node.children.length; i++) {
          var child = buildTreeNode(flatTree, node.children[i])
          if (child) {
            child.parent = null
            children.push(child)
          }
        }
      }
      return {
        type: 'element',
        tagName: node.tagName,
        attributes: node.attributes || {},
        isVisible: node.isVisible || false,
        isInteractive: node.isInteractive || false,
        isTopElement: node.isTopElement || false,
        isNew: node.isNew || false,
        highlightIndex: node.highlightIndex,
        parent: null,
        children: children,
        extra: node.extra || {},
      }
    }
  }

  function setParentReferences(node, parent) {
    node.parent = parent || null
    for (var i = 0; i < node.children.length; i++) {
      setParentReferences(node.children[i], node)
    }
  }

  /**
   * 检查文本节点是否有带 highlightIndex 的祖先
   * 有则跳过（文本已被父元素的 >text 包含）
   */
  function hasParentWithHighlightIndex(node) {
    var current = node.parent
    while (current) {
      if (current.type === 'element' && current.highlightIndex !== undefined) {
        return true
      }
      current = current.parent
    }
    return false
  }

  /**
   * 收集元素内部所有文本，直到遇到下一个可交互子元素为止
   */
  function getAllTextTillNextClickableElement(node, maxDepth) {
    if (maxDepth === undefined) maxDepth = -1
    var textParts = []

    function collectText(currentNode, currentDepth) {
      if (maxDepth !== -1 && currentDepth > maxDepth) return
      if (
        currentNode.type === 'element' &&
        currentNode !== node &&
        currentNode.highlightIndex !== undefined
      ) {
        return
      }
      if (currentNode.type === 'text' && currentNode.text) {
        textParts.push(currentNode.text)
      } else if (currentNode.type === 'element') {
        for (var i = 0; i < currentNode.children.length; i++) {
          collectText(currentNode.children[i], currentDepth + 1)
        }
      }
    }
    collectText(node, 0)
    return textParts.join('\n').trim()
  }

  /**
   * 将扁平 DOM 树序列化为 LLM 可读的缩进文本
   * 可交互元素用 [index]<tag attr=v>text /> 标记
   * 新元素用 *[index] 标记
   * 可滚动元素附加 data-scrollable 属性
   */
  function flatTreeToString(flatTree, includeAttributes, keepSemanticTags) {
    if (!includeAttributes) includeAttributes = []
    if (keepSemanticTags === undefined) keepSemanticTags = false

    var includeAttrs = includeAttributes.concat(DEFAULT_INCLUDE_ATTRIBUTES)

    var rootNode = buildTreeNode(flatTree, flatTree.rootId)
    if (!rootNode) return ''
    setParentReferences(rootNode, null)

    var result = []

    function processNode(node, depth) {
      var nextDepth = depth
      var depthStr = ''
      for (var d = 0; d < depth; d++) depthStr += '\t'

      if (node.type === 'element') {
        var isSemantic = keepSemanticTags && node.tagName && SEMANTIC_TAGS[node.tagName]

        // 带 highlightIndex 的可交互元素
        if (node.highlightIndex !== undefined) {
          nextDepth += 1

          var text = getAllTextTillNextClickableElement(node)
          var attributesHtmlStr = ''

          if (includeAttrs.length > 0) {
            var attributesToInclude = matchAttributes(node.attributes, includeAttrs)

            // 值去重：多个属性值相同（>5字符）只保留第一个
            var keys = Object.keys(attributesToInclude)
            if (keys.length > 1) {
              var keysToRemove = {}
              var seenValues = {}
              for (var k = 0; k < keys.length; k++) {
                var key = keys[k]
                var value = attributesToInclude[key]
                if (value.length > 5) {
                  if (seenValues.hasOwnProperty(value)) {
                    keysToRemove[key] = true
                  } else {
                    seenValues[value] = key
                  }
                }
              }
              for (var rm in keysToRemove) {
                delete attributesToInclude[rm]
              }
            }

            // role 与 tagName 相同则去除
            if (attributesToInclude.role === node.tagName) {
              delete attributesToInclude.role
            }

            // 属性值与文本内容相同时去除
            var dupAttrs = ['aria-label', 'placeholder', 'title']
            for (var di = 0; di < dupAttrs.length; di++) {
              var attr = dupAttrs[di]
              if (
                attributesToInclude[attr] &&
                attributesToInclude[attr].toLowerCase().trim() === text.toLowerCase().trim()
              ) {
                delete attributesToInclude[attr]
              }
            }

            var remainingKeys = Object.keys(attributesToInclude)
            if (remainingKeys.length > 0) {
              var parts = []
              for (var pi = 0; pi < remainingKeys.length; pi++) {
                parts.push(remainingKeys[pi] + '=' + capTextLength(attributesToInclude[remainingKeys[pi]], 20))
              }
              attributesHtmlStr = parts.join(' ')
            }
          }

          var highlightIndicator = node.isNew
            ? '*[' + node.highlightIndex + ']'
            : '[' + node.highlightIndex + ']'
          var line = depthStr + highlightIndicator + '<' + (node.tagName || '')

          if (attributesHtmlStr) {
            line += ' ' + attributesHtmlStr
          }

          // 可滚动数据
          if (node.extra && node.extra.scrollable) {
            var scrollDataText = ''
            if (node.extra.scrollData) {
              if (node.extra.scrollData.left) scrollDataText += 'left=' + node.extra.scrollData.left + ', '
              if (node.extra.scrollData.top) scrollDataText += 'top=' + node.extra.scrollData.top + ', '
              if (node.extra.scrollData.right) scrollDataText += 'right=' + node.extra.scrollData.right + ', '
              if (node.extra.scrollData.bottom) scrollDataText += 'bottom=' + node.extra.scrollData.bottom
            }
            scrollDataText = scrollDataText.replace(/,\s*$/, '')
            if (scrollDataText) {
              line += ' data-scrollable="' + scrollDataText + '"'
            }
          }

          if (text) {
            var trimmedText = text.trim()
            if (!attributesHtmlStr) line += ' '
            line += '>' + trimmedText
          } else if (!attributesHtmlStr) {
            line += ' '
          }
          line += ' />'
          result.push(line)
        }

        // 语义标签处理
        var emitSemantic = isSemantic && node.highlightIndex === undefined
        var mark = emitSemantic ? result.length : -1

        if (emitSemantic) {
          result.push(depthStr + '<' + node.tagName + '>')
          nextDepth += 1
        }

        for (var c = 0; c < node.children.length; c++) {
          processNode(node.children[c], nextDepth)
        }

        if (emitSemantic) {
          if (result.length === mark + 1) {
            result.pop()
          } else {
            result.push(depthStr + '</' + node.tagName + '>')
          }
        }
      } else if (node.type === 'text') {
        // 文本节点：没有高亮祖先 + 父元素可见且未被遮挡时才输出
        if (hasParentWithHighlightIndex(node)) return

        if (
          node.parent &&
          node.parent.type === 'element' &&
          node.parent.isVisible &&
          node.parent.isTopElement
        ) {
          result.push(depthStr + (node.text || ''))
        }
      }
    }

    processNode(rootNode, 0)
    return result.join('\n')
  }

  /**
   * 从扁平树构建 highlightIndex → 可交互节点的映射
   */
  function getSelectorMap(flatTree) {
    var selectorMap = {}
    for (var key in flatTree.map) {
      var node = flatTree.map[key]
      if (node.isInteractive && typeof node.highlightIndex === 'number') {
        selectorMap[node.highlightIndex] = node
      }
    }
    return selectorMap
  }

  /**
   * 从序列化文本反向解析 highlightIndex → 文本行（用于操作日志）
   */
  function getElementTextMap(simplifiedHTML) {
    var lines = simplifiedHTML.split('\n')
    var elementTextMap = {}
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim()
      if (line.length === 0) continue
      var match = /^\[(\d+)\]<[^>]+>([^<]*)/.exec(line)
      if (match) {
        var index = parseInt(match[1], 10)
        elementTextMap[index] = line
      }
    }
    return elementTextMap
  }

  /**
   * 采集页面尺寸和滚动信息，供 LLM 理解"还有多少内容未可见"
   */
  function getPageInfo() {
    var viewport_width = window.innerWidth
    var viewport_height = window.innerHeight

    var page_width = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth || 0)
    var page_height = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight || 0
    )

    var scroll_x = window.scrollX || window.pageXOffset || document.documentElement.scrollLeft || 0
    var scroll_y = window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0

    var pixels_below = Math.max(0, page_height - (window.innerHeight + scroll_y))
    var pixels_right = Math.max(0, page_width - (window.innerWidth + scroll_x))

    return {
      viewport_width: viewport_width,
      viewport_height: viewport_height,
      page_width: page_width,
      page_height: page_height,
      scroll_x: scroll_x,
      scroll_y: scroll_y,
      pixels_above: scroll_y,
      pixels_below: pixels_below,
      pages_above: viewport_height > 0 ? scroll_y / viewport_height : 0,
      pages_below: viewport_height > 0 ? pixels_below / viewport_height : 0,
      total_pages: viewport_height > 0 ? page_height / viewport_height : 0,
      current_page_position: scroll_y / Math.max(1, page_height - viewport_height),
      pixels_left: scroll_x,
      pixels_right: pixels_right,
    }
  }

  // 暴露到全局
  window.__DOM_SERIALIZE__ = {
    getFlatTree: getFlatTree,
    flatTreeToString: flatTreeToString,
    getSelectorMap: getSelectorMap,
    getElementTextMap: getElementTextMap,
    getPageInfo: getPageInfo,
    resolveViewportExpansion: function (ve) {
      return ve !== undefined ? ve : DEFAULT_VIEWPORT_EXPANSION
    },
  }
})()
