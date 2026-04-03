import mammoth from 'mammoth'

/**
 * Convert DOCX file to HTML with highlighted placeholders
 * @param {File} file - DOCX file object
 * @returns {Promise<{html: string, fields: string[]}>}
 */
export async function convertDocxToHtml(file) {
  try {
    const arrayBuffer = await file.arrayBuffer()

    // Configure mammoth to preserve some formatting
    const result = await mammoth.convertToHtml({ arrayBuffer }, {
      styleMap: [
        "p[style-name='Heading 1'] => h1:fresh",
        "p[style-name='Heading 2'] => h2:fresh",
        "p[style-name='Heading 3'] => h3:fresh"
      ],
      includeDefaultStyleMap: true
    })

    let html = result.value

    // Highlight mail merge placeholders: «FieldName»
    // This regex matches « followed by any characters followed by »
    html = html.replace(/«([^»]+)»/g, (match, fieldName) => {
      return `<span class="mail-merge-placeholder" data-field="${fieldName.trim()}" contenteditable="false">«${fieldName.trim()}»</span>`
    })

    // Extract field names from the HTML
    const placeholderRegex = /«([^»]+)»/g
    const fields = new Set()
    let match
    while ((match = placeholderRegex.exec(result.value)) !== null) {
      fields.add(match[1].trim())
    }

    return {
      html,
      fields: Array.from(fields),
      messages: result.messages
    }
  } catch (error) {
    console.error('Error converting DOCX to HTML:', error)
    throw new Error('Failed to convert document. Please ensure it is a valid .docx file.')
  }
}

/**
 * Generate CSS for placeholder highlighting and document formatting
 * @returns {string}
 */
export function getPlaceholderStyles() {
  return `
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
    .mail-merge-placeholder:focus {
      outline: 3px solid #ff6b6b;
      outline-offset: 2px;
    }

    /* Document formatting styles */
    .editor-content {
      font-family: Calibri, Arial, sans-serif;
      line-height: 1.15;
    }

    .editor-content h1 {
      font-size: 24pt;
      font-weight: bold;
      margin: 12pt 0;
      color: #2c3e50;
    }

    .editor-content h2 {
      font-size: 18pt;
      font-weight: bold;
      margin: 10pt 0;
      color: #34495e;
    }

    .editor-content h3 {
      font-size: 14pt;
      font-weight: bold;
      margin: 8pt 0;
      color: #7f8c8d;
    }

    .editor-content p {
      margin: 6pt 0;
      min-height: 1em;
    }

    /* Table styles */
    .editor-content .docx-table {
      border-collapse: collapse;
      width: 100%;
      margin: 10px 0;
    }

    .editor-content table {
      border-collapse: collapse;
      width: 100%;
      margin: 10px 0;
    }

    .editor-content table td,
    .editor-content table th {
      border: 1px solid #ccc;
      padding: 5px;
      vertical-align: top;
    }

    .editor-content table th {
      background-color: #f5f5f5;
      font-weight: bold;
      text-align: center;
    }

    /* Preserve formatting in spans */
    .editor-content span[style] {
      white-space: pre-wrap;
    }

    /* Handle tabs and spacing */
    .editor-content p[style*="text-align: center"] {
      text-align: center;
    }

    .editor-content p[style*="text-align: right"] {
      text-align: right;
    }

    .editor-content p[style*="text-align: justify"] {
      text-align: justify;
    }
  `
}
