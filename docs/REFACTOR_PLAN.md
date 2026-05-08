# Plan Refactor: Migrate sang loadfix/python-docx

## Tổng quan

**File hiện tại**: `backend/docx_editor.py` - 3383 dòng, 1 class `DocxFullEditor` với 50+ methods
**Thư viện mới**: `loadfix/python-docx` - fork mở rộng với 100+ tính năng OOXML bổ sung

## Phân tích hiện tại

### Các nhóm chức năng chính:
1. **Text manipulation** (15 methods): replace, insert, delete, search
2. **Formatting** (12 methods): font, paragraph, cell formatting
3. **Table operations** (8 methods): borders, merging, cells
4. **Document traversal** (10 methods): paragraphs, runs, segments
5. **Merge fields** (8 methods): create, read, modify placeholders
6. **Utility** (7 methods): normalize, validate, helpers

### Vấn đề với code hiện tại:
- **XML manipulation thủ công**: Nhiều code XPath với `find()`, `findall()`
- **Complex segment logic**: `_extract_all_text_runs()`, `_collect_paragraph_text_segments()` rất phức tạp
- **Missing features**: Không hỗ trợ bookmarks, content controls, fields API mới
- **Code duplication**: Pattern lặp lại ở nhiều methods

## Lợi ích từ loadfix/python-docx

### Features mới có thể tận dụng:

1. **Search & Replace API** (trong FEATURES.md):
   ```python
   document.search_and_replace(pattern, replacement, regex=True)
   document.search_and_replace(pattern, replacement, tables=True, headers=True)
   ```

2. **Bookmarks** (thay vì placeholder phức tạp):
   ```python
   bookmark = document.bookmarks['bookmark_name']
   bookmark.text = 'New text'
   ```

3. **Content Controls (SDTs)**:
   ```python
   for sdt in document.content_controls:
       if sdt.tag == 'plain_text':
           sdt.text = 'New value'
   ```

4. **Fields API**:
   ```python
   for field in document.fields:
       if field.type == 'MERGEFIELD':
           field.result = 'New value'
   ```

5. **Enhanced Table Operations**:
   ```python
   cell.borders = {'top': {'style': 'single', 'size': 4, 'color': 'auto'}}
   table.copy_rows_from(source_table)
   ```

6. **Simplified XML access**:
   ```python
   # XPath built-in
   for p in document.xpath('.//w:p'):
       ...
   ```

## Plan từng chặng

### PHẦN 1: SETUP & ASSESSMENT (Test kỹ)
**Mục tiêu**: Cài đặt thư viện mới và test backward compatibility

**Tasks**:
1. ✅ Verify `loadfix/python-docx` đã có trong requirements.txt
2. Test basic operations mở document, đọc, save
3. Run existing tests để đảm bảo không regressions
4. Document API differences

**Test cases**:
```python
def test_basic_operations():
    editor = DocxFullEditor('test.docx')
    assert editor.doc is not None
    editor.save('output.docx')
```

**Success criteria**:
- All existing tests pass
- Document opens/closes without errors
- No XML corruption

---

### PHẦN 2: SIMPLIFY TEXT MANIPULATION
**Mục tiêu**: Replace thủ công XML search/replace với built-in API

**Methods to refactor**:
- `_replace_text_in_segments()`
- `replace_paragraph_text_at_index()`
- `replace_text_at_position()`
- `_modify_segment_text()`

**Old code pattern**:
```python
# Manual XML traversal
for seg in target_segments:
    element = seg.get('element')
    if element is None:
        continue
    t_elements = element.findall(f"{self.w_ns}t")
    for t_elem in t_elements:
        t_elem.text = new_text
```

**New code pattern**:
```python
# Using search_and_replace API
for paragraph in self.doc.paragraphs:
    if pattern in paragraph.text:
        self.doc.search_and_replace(
            pattern=pattern,
            replacement=new_text,
            regex=False
        )
```

**Test cases**:
```python
def test_replace_simple_text():
    # Test simple text replacement
    editor.replace_text_at_position(
        paragraph_index=0,
        start_idx=10,
        end_idx=20,
        new_text='Hello'
    )
    assert 'Hello' in editor.doc.paragraphs[0].text

def test_replace_with_placeholders():
    # Test replacement with merge fields preserved
    editor.replace_paragraph_text_at_index(0, '«name» is here')
    assert '«name»' in editor.doc.paragraphs[0].text
```

**Success criteria**:
- All text operations work
- Formatting preserved
- Merge fields preserved
- Tests pass

---

### PHẦN 3: USE BOOKMARKS/CONTENT CONTROLS
**Mục tiêu**: Replace merge field placeholders với bookmarks/SDTs

**Why**: Bookmarks và Content Controls dễ quản lý hơn merge fields

**Methods to add**:
```python
def insert_bookmark(self, name: str, text: str):
    """Insert bookmark at current position"""
    bookmark = self.doc.add_bookmark(name, text)
    return bookmark

def update_bookmark(self, name: str, new_text: str):
    """Update bookmark text"""
    if name in self.doc.bookmarks:
        self.doc.bookmarks[name].text = new_text

def get_all_bookmarks(self) -> Dict[str, str]:
    """Get all bookmarks with their text"""
    return {bm.name: bm.text for bm in self.doc.bookmarks}
```

**Test cases**:
```python
def test_bookmark_operations():
    editor.insert_bookmark('client_name', 'John Doe')
    assert editor.get_all_bookmarks()['client_name'] == 'John Doe'

    editor.update_bookmark('client_name', 'Jane Smith')
    assert editor.get_bookmarks()['client_name'] == 'Jane Smith'
```

**Success criteria**:
- Bookmarks created/read/updated correctly
- Backward compatible with merge fields
- Document structure valid

---

### PHẦN 4: SIMPLIFY FORMATTING CODE
**Mục tiêu**: Use built-in formatting APIs thay vì XML manipulation

**Methods to refactor**:
- `_extract_run_format()`
- `apply_format_at_position()`
- `apply_paragraph_formatting()`
- `_copy_run_formatting()`

**Old code pattern**:
```python
# Manual XML property access
rpr = run._r.get_or_add_rPr()
bold_elem = rpr.find(f'{self.w_ns}b')
if bold_elem is not None:
    val = bold_elem.get(f'{self.w_ns}val', '1')
    format_info['bold'] = val != '0'
```

**New code pattern**:
```python
# Using python-docx API (enhanced in loadfix)
format_info = {
    'bold': run.bold,
    'italic': run.italic,
    'underline': run.underline,
    'color': run.font.color.rgb if run.font.color else None,
    'size': run.font.size,
}
```

**Test cases**:
```python
def test_extract_format():
    editor.apply_format_at_position(
        paragraph_index=0,
        start_idx=0,
        end_idx=10,
        bold=True,
        italic=True
    )
    fmt = editor.get_format(paragraph_index=0, offset=5)
    assert fmt['bold'] == True
    assert fmt['italic'] == True
```

**Success criteria**:
- Formatting applied correctly
- Code 50% shorter
- More readable

---

### PHẦN 5: ENHANCED TABLE OPERATIONS
**Mục tiêu**: Use enhanced table API

**Methods to refactor**:
- `set_cell_borders()`
- `get_cell_format()`
- `set_cell_format()`

**Old code pattern**:
```python
# Manual XML border manipulation
tc_borders = tc_pr.find(qn('w:tcBorders'))
if tc_borders is None:
    tc_borders = OxmlElement('w:tcBorders')
    tc_pr.append(tc_borders)

border = OxmlElement(f'w:{side}')
border.set(qn('w:val'), border_style)
border.set(qn('w:sz'), str(border_size))
```

**New code pattern**:
```python
# Using enhanced API
cell.borders = {
    'top': {'style': 'single', 'size': 4, 'color': 'auto'},
    'bottom': {'style': 'single', 'size': 4, 'color': 'auto'},
    'left': {'style': 'single', 'size': 4, 'color': 'auto'},
    'right': {'style': 'single', 'size': 4, 'color': 'auto'},
}
```

**Test cases**:
```python
def test_table_borders():
    editor.set_cell_borders(
        table_index=0,
        row_index=0,
        col_index=0,
        borders={'top': {'style': 'double', 'size': 6, 'color': 'FF0000'}}
    )
    fmt = editor.get_cell_format(0, 0, 0)
    assert fmt['borders']['top']['style'] == 'double'
```

**Success criteria**:
- Table formatting works
- Code 70% shorter
- Supports more border styles

---

### PHẦN 6: CLEANUP & OPTIMIZE
**Mục tiêu**: Remove unused code, optimize performance

**Tasks**:
1. Remove duplicate code
2. Optimize document traversal (use built-in `iter_inner_content()`)
3. Remove unused helper methods
4. Add docstrings
5. Type hints improvement

**Expected reduction**:
- Current: 3383 lines
- Target: ~2000 lines (40% reduction)

---

### PHẦN 7: TESTING & VALIDATION
**Mục tiêu**: Comprehensive test coverage

**Test suites**:
1. Unit tests cho mỗi method
2. Integration tests cho workflows
3. Edge case tests (empty documents, corrupted files, etc.)
4. Performance benchmarks

**Test coverage target**: 80%+

---

## Timeline Estimate

| Phần | Duration | Dependencies |
|------|----------|--------------|
| Phần 1: Setup | 1 day | - |
| Phần 2: Text manipulation | 2-3 days | Phần 1 |
| Phần 3: Bookmarks/SDTs | 2 days | Phần 2 |
| Phần 4: Formatting | 2-3 days | Phần 2 |
| Phần 5: Tables | 1-2 days | Phần 4 |
| Phần 6: Cleanup | 1-2 days | Phần 2-5 |
| Phần 7: Testing | 2-3 days | Phần 1-6 |
| **Total** | **13-19 days** | |

---

## Risk Mitigation

### Risk 1: API incompatibility
**Mitigation**: Phần 1 test kỹ backward compatibility, maintain wrapper methods

### Risk 2: XML corruption
**Mitigation**: Test với real documents, validate XML structure sau mỗi operation

### Risk 3: Performance regression
**Mitigation**: Benchmark operations, use built-in iterators thay vì manual loops

### Risk 4: Breaking changes
**Mitigation**: Version bump, maintain deprecated methods với warnings

---

## Success Metrics

1. **Code reduction**: 40% fewer lines
2. **Performance**: 20% faster operations
3. **Features**: +10 new features (bookmarks, SDTs, fields, etc.)
4. **Test coverage**: 80%+
5. **User-facing**: No breaking API changes

---

## Next Steps

1. Review và approve plan
2. Setup test environment
3. Start với Phần 1: Setup & Assessment
