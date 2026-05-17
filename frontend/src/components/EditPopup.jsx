import { useState, useEffect } from 'react'

function EditPopup({ selectedText, onFormatApplied, onClose }) {
  const [originalFormat, setOriginalFormat] = useState(null)
  const [format, setFormat] = useState({
    bold: false,
    italic: false,
    underline: false,
    strikethrough: false,
    subscript: false,
    superscript: false,
    color: '#000000',
    highlight: null,
    fontSize: 12,
    fontName: 'Times New Roman',
    allCaps: false,
    alignment: 'left'
  })
  const [paragraphFormat, setParagraphFormat] = useState({
    lineSpacing: 1.0,
    spaceBefore: 0,
    spaceAfter: 0,
    firstLineIndent: 0
  })
  const [showParagraphOptions, setShowParagraphOptions] = useState(false)
  const [paragraphFormatChanged, setParagraphFormatChanged] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Initialize format from selectedText when component mounts or selectedText changes
  useEffect(() => {
    if (selectedText?.format) {
      setFormat(selectedText.format)
      setOriginalFormat(selectedText.format)
    }
  }, [selectedText])

  const hasFormatChanged = () => {
    const textFormatChanged = !originalFormat || Object.keys(format).some(key => 
      format[key] !== (originalFormat[key] ?? (key === 'highlight' ? null : key === 'alignment' ? 'left' : false))
    )
    return textFormatChanged || paragraphFormatChanged
  }

  const handleApplyFormat = async () => {
    if (!hasFormatChanged()) {
      onClose()
      return
    }

    setSubmitting(true)
    try {
      const formatData = {
        selectedText: selectedText?.text,
        format: format,
        type: 'format',
        blockIndex: selectedText?.blockIndex,
        startOffset: selectedText?.offset,
        endOffset: selectedText?.endOffset,
        paraInCell: selectedText?.paraInCell
      }

      if (showParagraphOptions) {
        formatData.paragraphFormat = paragraphFormat
      }

      await onFormatApplied(formatData)
      onClose()
    } catch (error) {
      console.error('Format application failed:', error)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-6 right-6 bg-white shadow-2xl rounded-2xl border border-slate-100 w-[420px] z-50 animate-in slide-in-from-bottom-4 duration-300 flex flex-col max-h-[85vh]">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-50 flex justify-between items-center bg-slate-50/50 rounded-t-2xl">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-indigo-100 text-indigo-600 rounded-lg flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg>
          </div>
          <h3 className="font-bold text-slate-800 tracking-tight">Định dạng văn bản</h3>
        </div>
        <button onClick={onClose} className="w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-all">✕</button>
      </div>

      <div className="p-5 overflow-y-auto space-y-6">
        {/* Selected text preview */}
        <div>
          <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Văn bản đang chọn</label>
          <div className="bg-slate-50 px-4 py-3 rounded-xl text-sm text-slate-600 border border-slate-100 italic font-medium leading-relaxed whitespace-pre-wrap">
            "{selectedText?.text || '...'}"
          </div>
        </div>

        {/* Font & Style */}
        <div className="space-y-4">
           <div className="flex gap-4">
              <div className="flex-1">
                <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Phông chữ</label>
                <select
                  value={format.fontName}
                  onChange={(e) => setFormat({ ...format, fontName: e.target.value })}
                  className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                >
                  <option value="Times New Roman">Times New Roman</option>
                  <option value="Arial">Arial</option>
                  <option value="Calibri">Calibri</option>
                  <option value="Verdana">Verdana</option>
                  <option value="Georgia">Georgia</option>
                </select>
              </div>
              <div className="w-24">
                <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Cỡ chữ</label>
                <input
                  type="number"
                  value={format.fontSize}
                  onChange={(e) => setFormat({ ...format, fontSize: parseInt(e.target.value) || 12 })}
                  className="w-full bg-white border border-slate-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                />
              </div>
           </div>

           <div className="flex flex-wrap gap-2">
              {[
                { id: 'bold', label: 'B', icon: 'M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z' },
                { id: 'italic', label: 'I', icon: 'M19 4h-9M14 20H5M15 4L9 20' },
                { id: 'underline', label: 'U', icon: 'M6 3v7a6 6 0 0 0 12 0V3M4 21h16' },
                { id: 'strikethrough', label: 'S', icon: 'M5 12h14M4 19c2 0 5-1 5-4s-3-4-5-4 5-1 5-4-3-4-5-4 11 0 11 0' }
              ].map(style => (
                <button
                  key={style.id}
                  onClick={() => setFormat({ ...format, [style.id]: !format[style.id] })}
                  className={`w-10 h-10 flex items-center justify-center rounded-xl border transition-all ${format[style.id] ? 'bg-indigo-600 text-white border-indigo-600 shadow-md shadow-indigo-100' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
                >
                  <span
                    className={`text-sm font-bold ${
                      style.id === 'italic'
                        ? 'italic'
                        : style.id === 'underline'
                          ? 'underline'
                          : style.id === 'strikethrough'
                            ? 'line-through'
                            : ''
                    }`}
                  >
                    {style.label}
                  </span>
                </button>
              ))}
              <div className="w-px h-10 bg-slate-100 mx-1"></div>
              {['subscript', 'superscript'].map(type => (
                <button
                  key={type}
                  onClick={() => setFormat({ ...format, subscript: type === 'subscript' ? !format.subscript : false, superscript: type === 'superscript' ? !format.superscript : false })}
                  className={`w-10 h-10 flex items-center justify-center rounded-xl border transition-all ${format[type] ? 'bg-indigo-600 text-white border-indigo-600 shadow-md' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
                >
                  <span className="text-[10px] font-bold">x{type === 'subscript' ? '₂' : '²'}</span>
                </button>
              ))}
           </div>
        </div>

        {/* Colors */}
        <div className="grid grid-cols-2 gap-4">
           <div>
              <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Màu chữ</label>
              <div className="flex items-center gap-2 p-1.5 bg-white border border-slate-200 rounded-xl">
                <input type="color" value={format.color} onChange={(e) => setFormat({ ...format, color: e.target.value })} className="w-8 h-8 rounded-lg cursor-pointer border-0 bg-transparent" />
                <span className="text-xs font-mono font-bold text-slate-500 uppercase">{format.color}</span>
              </div>
           </div>
           <div>
              <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Màu nền</label>
              <div className="flex items-center gap-2 p-1.5 bg-white border border-slate-200 rounded-xl">
                <input type="color" value={format.highlight || '#ffffff'} onChange={(e) => setFormat({ ...format, highlight: e.target.value })} className="w-8 h-8 rounded-lg cursor-pointer border-0 bg-transparent" />
                <button onClick={() => setFormat({ ...format, highlight: null })} className="p-1 hover:bg-red-50 text-red-400 rounded transition-colors ml-auto"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
              </div>
           </div>
        </div>

        {/* Alignment */}
        <div>
           <label className="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Căn lề</label>
           <div className="flex p-1 bg-slate-100 rounded-xl gap-1">
              {[
                { id: 'left', icon: 'M4 6h16M4 12h10M4 18h16' },
                { id: 'center', icon: 'M4 6h16M7 12h10M4 18h16' },
                { id: 'right', icon: 'M4 6h16M10 12h10M4 18h16' },
                { id: 'justify', icon: 'M4 6h16M4 12h16M4 18h16' }
              ].map(align => (
                <button
                  key={align.id}
                  onClick={() => setFormat({ ...format, alignment: align.id })}
                  className={`flex-1 py-2 flex items-center justify-center rounded-lg transition-all ${format.alignment === align.id ? 'bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200' : 'text-slate-400 hover:text-slate-600'}`}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d={align.icon}/></svg>
                </button>
              ))}
           </div>
        </div>

        {/* Paragraph Options Toggle */}
        <div className="pt-2">
          <button 
            onClick={() => setShowParagraphOptions(!showParagraphOptions)}
            className="flex items-center gap-2 text-indigo-600 text-xs font-bold hover:text-indigo-700 transition-colors"
          >
            <svg 
              xmlns="http://www.w3.org/2000/svg" 
              width="14" height="14" 
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" 
              className={`transition-transform duration-200 ${showParagraphOptions ? 'rotate-90' : ''}`}
            >
              <path d="m9 18 6-6-6-6"/>
            </svg>
            TÙY CHỌN ĐOẠN VĂN (DÃN DÒNG, THỤT LỀ...)
          </button>
        </div>

        {/* Paragraph Advanced Options */}
        {showParagraphOptions && (
          <div className="space-y-4 p-4 bg-indigo-50/50 rounded-2xl border border-indigo-100/50 animate-in fade-in zoom-in-95 duration-200">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-2">Dãn dòng</label>
                <select
                  value={paragraphFormat.lineSpacing}
                  onChange={(e) => {
                    setParagraphFormat({ ...paragraphFormat, lineSpacing: parseFloat(e.target.value) });
                    setParagraphFormatChanged(true);
                  }}
                  className="w-full bg-white border border-indigo-100 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                >
                  <option value="1.0">Đơn (1.0)</option>
                  <option value="1.15">1.15</option>
                  <option value="1.5">1.5</option>
                  <option value="2.0">Kép (2.0)</option>
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-2">Thụt lề đầu</label>
                <div className="relative">
                  <input
                    type="number"
                    value={paragraphFormat.firstLineIndent}
                    onChange={(e) => {
                      setParagraphFormat({ ...paragraphFormat, firstLineIndent: parseInt(e.target.value) || 0 });
                      setParagraphFormatChanged(true);
                    }}
                    className="w-full bg-white border border-indigo-100 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-slate-400">pt</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-2">Cách trên</label>
                <div className="relative">
                  <input
                    type="number"
                    value={paragraphFormat.spaceBefore}
                    onChange={(e) => {
                      setParagraphFormat({ ...paragraphFormat, spaceBefore: parseInt(e.target.value) || 0 });
                      setParagraphFormatChanged(true);
                    }}
                    className="w-full bg-white border border-indigo-100 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-slate-400">pt</span>
                </div>
              </div>
              <div>
                <label className="block text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-2">Cách dưới</label>
                <div className="relative">
                  <input
                    type="number"
                    value={paragraphFormat.spaceAfter}
                    onChange={(e) => {
                      setParagraphFormat({ ...paragraphFormat, spaceAfter: parseInt(e.target.value) || 0 });
                      setParagraphFormatChanged(true);
                    }}
                    className="w-full bg-white border border-indigo-100 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 outline-none transition-all pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-slate-400">pt</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Hyperlink */}
        <button
          onClick={() => {
            if (selectedText?.blockIndex !== undefined && selectedText?.offset !== undefined) {
               onClose()
               selectedText.onOpenHyperlink(selectedText.blockIndex, selectedText.offset, selectedText.endOffset, selectedText.text)
            }
          }}
          className="w-full py-3 px-4 bg-blue-50 text-blue-700 rounded-xl border border-blue-100 font-bold text-sm flex items-center justify-center gap-2 hover:bg-blue-100 transition-all active:scale-95"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
          Chèn Hyperlink
        </button>
      </div>

      {/* Footer Actions */}
      <div className="p-5 border-t border-slate-50 flex gap-3">
        <button
          onClick={handleApplyFormat}
          disabled={submitting || !hasFormatChanged()}
          className="flex-[2] bg-indigo-600 text-white py-3 rounded-xl font-bold text-sm hover:bg-indigo-700 disabled:bg-slate-200 transition-all shadow-lg shadow-indigo-100 active:scale-95"
        >
          {submitting ? 'Đang lưu...' : 'Lưu thay đổi'}
        </button>
        <button onClick={onClose} className="flex-1 bg-slate-100 text-slate-600 py-3 rounded-xl font-bold text-sm hover:bg-slate-200 transition-all active:scale-95">Hủy</button>
      </div>
    </div>
  )
}

export default EditPopup
