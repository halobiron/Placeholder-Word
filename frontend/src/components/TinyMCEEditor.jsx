import { Editor } from '@tinymce/tinymce-react'
import { useRef, useState } from 'react'

function TinyMCEEditor({ html, fields, onFieldDelete, onFieldAdd, onChange }) {
  const editorRef = useRef(null)
  const [showPlaceholderPanel, setShowPlaceholderPanel] = useState(false)

  // Extract field names from HTML
  const extractFieldsFromHtml = (content) => {
    const fieldRegex = /«([^»]+)»/g
    const foundFields = new Set()
    let match
    while ((match = fieldRegex.exec(content)) !== null) {
      foundFields.add(match[1].trim())
    }
    return Array.from(foundFields)
  }

  // Handle content changes
  const handleEditorChange = (content, editor) => {
    // Extract fields from content
    const currentFields = extractFieldsFromHtml(content)

    if (onChange) {
      onChange(content, currentFields)
    }
  }

  // Delete a placeholder
  const deletePlaceholder = (fieldName) => {
    if (!editorRef.current) return

    const editor = editorRef.current
    const content = editor.getContent()

    // Replace the placeholder with empty string
    const newContent = content.replace(
      new RegExp(`«${fieldName}»`, 'g'),
      ''
    )

    editor.setContent(newContent)

    if (onFieldDelete) {
      onFieldDelete(fieldName)
    }
  }

  // Insert a new merge field
  const insertMergeField = () => {
    const fieldName = prompt('Nhập tên field muốn thêm:')
    if (!fieldName || !fieldName.trim()) return

    const fieldNameTrimmed = fieldName.trim()

    if (!editorRef.current) return

    const editor = editorRef.current
    const placeholder = `«${fieldNameTrimmed}»`

    // Insert at cursor position
    editor.insertContent(
      `<span class="mail-merge-placeholder" data-field="${fieldNameTrimmed}" contenteditable="false">${placeholder}</span>&nbsp;`
    )

    if (onFieldAdd) {
      onFieldAdd(fieldNameTrimmed)
    }

    setShowPlaceholderPanel(false)
  }

  // Find and highlight a placeholder
  const findPlaceholder = (fieldName) => {
    if (!editorRef.current) return

    const editor = editorRef.current
    const content = editor.getContent()

    // Search for the placeholder
    const placeholderRegex = new RegExp(`«${fieldName}»`)
    if (!placeholderRegex.test(content)) {
      alert(`Không tìm thấy placeholder «${fieldName}»`)
      return
    }

    // Use TinyMCE's search to find and select
    editor.searchReplace(`«${fieldName}»`, `«${fieldName}»`, false, true, true, true)
  }

  return (
    <div className="tinymce-editor-wrapper">
      {/* Placeholder Management Panel */}
      {showPlaceholderPanel && (
        <div className="mb-4 p-4 bg-blue-50 border border-blue-300 rounded-lg">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-bold text-lg text-blue-900">
              Danh sách Placeholders ({fields.length})
            </h3>
            <button
              type="button"
              onClick={() => setShowPlaceholderPanel(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              ✕
            </button>
          </div>

          <div className="mb-3">
            <button
              type="button"
              onClick={insertMergeField}
              className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white rounded-lg font-medium"
            >
              + Thêm Field Mới
            </button>
          </div>

          {fields.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-60 overflow-y-auto">
              {fields.map((field, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between gap-2 p-2 bg-white rounded border border-blue-200 hover:shadow-sm transition-shadow"
                >
                  <span className="px-2 py-1 bg-blue-100 border border-blue-300 rounded font-mono text-sm">
                    {index + 1}. «{field}»
                  </span>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => findPlaceholder(field)}
                      className="px-2 py-1 bg-yellow-500 hover:bg-yellow-600 text-white rounded text-sm"
                      title="Tìm trong văn bản"
                    >
                      🔍
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm(`Xoá placeholder «${field}»?`)) {
                          deletePlaceholder(field)
                        }
                      }}
                      className="px-2 py-1 bg-red-500 hover:bg-red-600 text-white rounded text-sm"
                      title="Xoá placeholder"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-600 text-sm">Không tìm thấy placeholder nào trong tài liệu.</p>
          )}
        </div>
      )}

      {/* Toggle Panel Button */}
      <div className="mb-3 flex justify-end">
        <button
          type="button"
          onClick={() => setShowPlaceholderPanel(!showPlaceholderPanel)}
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium flex items-center gap-2"
        >
          📋 Fields ({fields.length})
        </button>
      </div>

      {/* TinyMCE Editor */}
      <Editor
        licenseKey="gpl"
        tinymceScriptSrc="/tinymce/tinymce.min.js"
        onInit={(evt, editor) => {
          editorRef.current = editor
        }}
        initialValue={html}
        onEditorChange={handleEditorChange}
        init={{
          height: 600,
          menubar: true,
          base_url: '/tinymce',
          suffix: '.min',

          plugins: [
            'advlist', 'autolink', 'lists', 'link', 'image', 'charmap', 'preview',
            'anchor', 'searchreplace', 'visualblocks', 'code', 'fullscreen',
            'insertdatetime', 'media', 'table', 'help', 'wordcount',
            'importcss', 'directionality'
          ],

          toolbar:
            'undo redo | formatselect | bold italic underline strikethrough | ' +
            'alignleft aligncenter alignright alignjustify | ' +
            'bullist numlist outdent indent | forecolor backcolor | ' +
            'table | link image | removeformat code fullscreen | help',

          toolbar_mode: 'wrappping',
          toolbar_groups: {
            alignment: {
              icon: 'align-left',
              tooltip: 'Alignment',
              items: 'alignleft aligncenter alignright alignjustify'
            },
            textstyle: {
              icon: 'format',
              tooltip: 'Text Style',
              items: 'bold italic underline strikethrough | forecolor backcolor | fontselect fontsizeselect formatselect'
            }
          },

          // Content styling
          content_style: `
            .mail-merge-placeholder {
              background: linear-gradient(120deg, #a8edea 0%, #fed6e3 100%);
              padding: 2px 6px;
              border-radius: 4px;
              font-weight: 600;
              color: #1e3a5f;
              border: 2px solid #4a90d9;
              cursor: pointer;
              user-select: none;
              display: inline-block;
              transition: all 0.2s ease;
            }
            .mail-merge-placeholder:hover {
              transform: scale(1.05);
              box-shadow: 0 2px 8px rgba(74, 144, 217, 0.3);
            }
            body {
              font-family: Calibri, Arial, sans-serif;
              font-size: 11pt;
              line-height: 1.15;
            }
          `,

          // Custom elements for mail merge placeholders
          valid_elements: '*[*]',
          extended_valid_elements: 'span[class|data-field|contenteditable|style]',

          // Table styling
          table_default_attributes: {
            'border': '1',
            'cellpadding': '5',
            'cellspacing': '0'
          },
          table_default_styles: {
            'border-collapse': 'collapse',
            'width': '100%'
          },
          table_responsive_width: true,

          // Font formats
          font_formats: 'Arial=arial,helvetica,sans-serif; Courier New=courier new,courier,monospace; Times New Roman=times new roman,times; Calibri=calibri',

          fontsize_formats: '8pt 9pt 10pt 11pt 12pt 14pt 16pt 18pt 20pt 24pt 28pt 36pt 48pt',

          formatselect: true,

          style_formats: [
            { title: 'Bold text', inline: 'b' },
            { title: 'Red text', inline: 'span', styles: { color: '#ff0000' } },
            { title: 'Red header', block: 'h1', styles: { color: '#ff0000' } },
            { title: 'Example 1', inline: 'span', classes: 'example1' },
            { title: 'Example 2', inline: 'span', classes: 'example2' }
          ],

          // Image upload
          images_upload_handler: (blobInfo, progress) => new Promise((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => {
              resolve(reader.result)
            }
            reader.onerror = () => {
              reject('Image upload failed')
            }
            reader.readAsDataURL(blobInfo.blob())
          }),

          // Setup callback
          setup: (editor) => {
            // Add custom command to insert merge field
            editor.addCommand('InsertMergeField', () => {
              const fieldName = prompt('Nhập tên field:')
              if (fieldName && fieldName.trim()) {
                const fieldNameTrimmed = fieldName.trim()
                editor.insertContent(
                  `<span class="mail-merge-placeholder" data-field="${fieldNameTrimmed}" contenteditable="false">«${fieldNameTrimmed}»</span>&nbsp;`
                )
              }
            })

            // Add button to toolbar for inserting merge field
            editor.ui.registry.addButton('mergefield', {
              text: '🔧 Field',
              icon: 'addcomment',
              tooltip: 'Thêm Merge Field',
              onAction: () => {
                editor.execCommand('InsertMergeField')
              }
            })

            // Handle placeholder clicks
            editor.on('click', (e) => {
              const target = e.target
              if (target.classList.contains('mail-merge-placeholder')) {
                const fieldName = target.getAttribute('data-field')
                console.log('Clicked placeholder:', fieldName)

                // Highlight the placeholder
                target.style.outline = '3px solid #ff6b6b'
                setTimeout(() => {
                  target.style.outline = ''
                }, 2000)
              }
            })
          },

          // Directionality for RTL support
          directionality: 'ltr',

          // Autoresize
          resize: true,

          // Status bar
          statusbar: true,
          elementpath: true,

          // Help
          help_tabs: [
            'shortcuts',
            'keyboardnav',
            'plugins'
          ]
        }}
      />

      {/* Custom CSS for additional styling */}
      <style>{`
        .tinymce-editor-wrapper .tox-tinymce {
          border-radius: 0.5rem;
        }

        /* Placeholder styling in editor */
        .mail-merge-placeholder {
          background: linear-gradient(120deg, #a8edea 0%, #fed6e3 100%);
          padding: 2px 6px;
          border-radius: 4px;
          font-weight: 600;
          color: #1e3a5f;
          border: 2px solid #4a90d9;
          cursor: pointer;
          user-select: none;
          display: inline-block;
          transition: all 0.2s ease;
        }

        .mail-merge-placeholder:hover {
          transform: scale(1.05);
          box-shadow: 0 2px 8px rgba(74, 144, 217, 0.3);
        }
      `}</style>
    </div>
  )
}

export default TinyMCEEditor
