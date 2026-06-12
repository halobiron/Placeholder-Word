# 🎯 Kế Hoạch Fine-Tune Model Cho Mail Merge System

## 📋 Tổng Quan

**Mục tiêu**: Fine-tune một LLM để cải thiện khả năng phân tích placeholder và context cho Mail Merge System
**Framework**: LlamaFactory (đã clone vào `backend/LlamaFactory`)
**Target Model**: Qwen3-4B-Instruct (khuyến nghị)
**Hardware**: Apple M4 (cần config đặc biệt hoặc dùng cloud)
**Timeline dự kiến**: 7-10 days

---

## 🎯 Mục Tiêu Cụ Thể

### 1. Smart Field Naming
Phân tích context để đặt tên placeholder thông minh cho các trường hợp:
- Basic: "Họ và tên: ..." → `ho_ten`
- Multi-line: "Tôi tên: ........ Số CMND: ........"
- Date patterns: "[Hà Nội], ngày... tháng... năm 20..."
- Checkbox: "□ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: ..."

### 2. Context Understanding
- Hiểu các biểu mẫu tiếng Việt phức tạp
- Xử lý multi-placeholders per line
- Recognize specific Vietnamese patterns (địa danh, năm học, etc.)

---

## 🧠 Model Selection

### Khuyến nghị: Qwen3-4B-Instruct

**Tại sao chọn Qwen3?**
- ✅ **Hỗ trợ tiếng Việt xuất sắc** - Tốt hơn Llama cho Chinese/Vietnamese
- ✅ **Kích thước phù hợp** - 4B params, train được với limited resources
- ✅ **Instruct-ready** - Đã instruction-tuned, dễ fine-tune
- ✅ **Community support tốt** - Nhiều examples trong LlamaFactory
- ✅ **Recent architecture** - Release 2025, technology hiện đại

**Alternatives:**
- **Llama 3.1-8B** - Popular hơn nhưng tốn resources hơn
- **DeepSeek-R1-Distill-Qwen-7B** - Reasoning mạnh nhưng overkill cho task này

---

## 💾 Dataset Preparation

### Format Dataset

```json
{
  "instruction": "Phân tích biểu mẫu Word và đặt tên placeholder theo snake_case tiếng Việt không dấu",
  "input": "Tôi tên: ........ Số CMND: ........",
  "output": "ho_ten, so_cmnd"
}
```

### Các Categories cần thiết

#### 1. Basic Placeholders (30 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word và đặt tên placeholder theo snake_case tiếng Việt không dấu",
  "input": "Họ và tên: ...........................................",
  "output": "ho_va_ten"
}
```

#### 2. Multi-Placeholders Per Line (40 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word và đặt tên tất cả placeholders theo snake_case tiếng Việt không dấu, phân tách bằng dấu phẩy",
  "input": "Tôi tên: ........ Số CMND: ........",
  "output": "ho_ten, so_cmnd"
}
```

#### 3. Date Patterns (25 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word và đặt tên placeholder cho ngày tháng năm, đặt tên theo tiếng Việt không dấu snake_case",
  "input": "[Hà Nội], ngày... tháng... năm 20...",
  "output": "ngay, thang, nam"
}
```

#### 4. Checkbox Patterns (25 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word với checkbox, đặt tên placeholder cho trường điền sau checkbox, bỏ qua checkbox text",
  "input": "□ Nghỉ không lương   □ Nghỉ bệnh    □ Khác: ..................",
  "output": "khac"
}
```

#### 5. Multi-line Placeholders (20 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word với placeholder kéo dài nhiều dòng, đặt tên theo ngữ cảnh",
  "input": "Lý do nghỉ phép:\n...........................................\n...........................................",
  "output": "ly_do_nghi_phep"
}
```

#### 6. Complex Vietnamese Patterns (30 examples)
```json
{
  "instruction": "Phân tích biểu mẫu Word tiếng Việt với các pattern đặc biệt (năm học, địa danh, etc.)",
  "input": "Năm học: 20... - 20...",
  "output": "nam_hoc"
}
```

### Dataset Structure

```
backend/LlamaFactory/data/
├── mail_merge_vi_train.json    # 145 examples (80%)
├── mail_merge_vi_val.json      # 18 examples (10%)
├── mail_merge_vi_test.json     # 18 examples (10%)
└── dataset_info.json          # Update registry
```

### Data Quality Guidelines

- **Consistency**: Cùng instruction format cho tất cả examples
- **Variety**: Cover tất cả Vietnamese form patterns
- **Edge cases**: Include các trường hợp khó (doubledots, special chars)
- **Real-world**: Dựa trên actual Vietnamese government/corporate forms

---

## 🖥️ Hardware Strategy

### Apple M4 Limitations
- ❌ Không hỗ trợ CUDA (NVIDIA)
- ⚠️ PyTorch MPS support còn hạn chế
- ✅ Có thể train local nhưng sẽ chậm

### 3 Options

#### Option 1: Local Training (MPS) - Khó khăn
```bash
# Cần install PyTorch với MPS support
pip install torch torchvision torchaudio

# Config thay đổi:
bf16: false
fp16: true
device: cpu  # hoặc mps nếu supported
```
**Pros**: Free, local
**Cons**: Rất chậm, limited memory

#### Option 2: Cloud Training - KHUYÊN DÙNG ⭐

**Google Colab Free Tier**
- GPU T4 miễn phí
- Perfect cho QLoRA 4-bit training
- 12GB VRAM enough cho Qwen3-4B QLoRA

**RunPod/Vast.ai**
- Rẻ hơn AWS/GCP ($0.20-0.50/hour)
- GPU RTX 3090/4090 available
- Estimate cost: $5-10 cho full training

**Google Cloud Platform**
- $300 free credit cho new users
- T4 GPU ~$0.25/hour

#### Option 3: Hybrid Approach
- Prepare data và config local
- Train trên cloud (Colab/RunPod)
- Download model về local
- Integrate vào system

---

## 📝 Implementation Steps

### Phase 1: Environment Setup (Day 1-2)

```bash
# 1. Install LlamaFactory
cd /Users/aiot/Documents/Placeholder-Word/backend/LlamaFactory
pip install -e .
pip install -r requirements/metrics.txt

# 2. Verify installation
llamafactory-cli version

# 3. (Optional) Setup cloud GPU
# Colab: https://colab.research.google.com/
# RunPod: https://www.runpod.io/
```

### Phase 2: Dataset Creation (Day 2-4)

```bash
# Create dataset files
cd backend/LlamaFactory/data

# Create training data with 170+ examples
touch mail_merge_vi_train.json
touch mail_merge_vi_val.json
touch mail_merge_vi_test.json
```

**Sample data creation script:**

```python
import json

examples = [
    {
        "instruction": "Phân tích biểu mẫu Word và đặt tên placeholder theo snake_case tiếng Việt không dấu",
        "input": "Họ và tên: ...........................................",
        "output": "ho_va_ten"
    },
    # ... add more examples
]

with open('mail_merge_vi_train.json', 'w', encoding='utf-8') as f:
    json.dump(examples, f, ensure_ascii=False, indent=2)
```

**Update dataset_info.json:**

```json
"mail_merge_vi": {
  "file_name": "mail_merge_vi_train.json",
  "formatting": "alpaca",
  "columns": {
    "prompt": "instruction",
    "query": "input",
    "response": "output"
  }
}
```

### Phase 3: Training Configuration (Day 4)

Create file: `backend/LlamaFactory/examples/mail_merge_lora_sft.yaml`

```yaml
### Model
model_name_or_path: Qwen/Qwen3-4B-Instruct
trust_remote_code: true

### Method
stage: sft
do_train: true
finetuning_type: lora
lora_rank: 16
lora_target: all
lora_alpha: 32

### Dataset
dataset: mail_merge_vi
template: qwen3
cutoff_len: 1024
max_samples: null
preprocessing_num_workers: 4
dataloader_num_workers: 2

### Output
output_dir: saves/mail_merge_qwen3_lora
logging_steps: 10
save_steps: 100
plot_loss: true
overwrite_output_dir: true
save_only_model: false
report_to: tensorboard

### Training
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
learning_rate: 5.0e-5
num_train_epochs: 5.0
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true

### Evaluation
val_size: 0.1
per_device_eval_batch_size: 2
eval_strategy: steps
eval_steps: 100
```

### Phase 4: Training Execution (Day 5-7)

#### Option A: Local Training (khó khăn)
```bash
cd backend/LlamaFactory
llamafactory-cli train examples/mail_merge_lora_sft.yaml
```

#### Option B: Cloud Training (khuyên dùng)

**Colab setup:**
```python
# Clone và install
!git clone --depth 1 https://github.com/hiyouga/LlamaFactory.git
%cd LlamaFactory
!pip install -e .

# Upload data files đến Colab
# Then run:
!llamafactory-cli train mail_merge_lora_sft.yaml
```

**Monitor training:**
- Watch loss curve (nên giảm xuống 0.5-1.0)
- Check validation accuracy
- Save checkpoints regularly

### Phase 5: Model Export (Day 7)

Create: `backend/LlamaFactory/examples/mail_merge_export.yaml`

```yaml
### Model
model_name_or_path: Qwen/Qwen3-4B-Instruct
adapter_name_or_path: saves/mail_merge_qwen3_lora
trust_remote_code: true

### Export
export_dir: saves/mail_merge_qwen3_merged
export_size: 2
export_device: cpu
export_legacy_format: false
```

Run export:
```bash
llamafactory-cli export examples/mail_merge_export.yaml
```

### Phase 6: Integration (Day 8-10)

#### 6.1. Model Inference Setup

Create inference script: `backend/mail_merge_model_inference.py`

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

class MailMergeFieldPredictor:
    def __init__(self, model_path="saves/mail_merge_qwen3_merged"):
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True
        )
    
    def predict_field_names(self, form_text: str) -> list:
        """Predict field names from form text"""
        prompt = f"""Phân tích biểu mẫu Word và đặt tên placeholder theo snake_case tiếng Việt không dấu.

Input: {form_text}
Output:"""
        
        inputs = self.tokenizer(prompt, return_tensors="pt")
        outputs = self.model.generate(**inputs, max_new_tokens=100)
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Parse output to get field names
        return self._parse_field_names(response)
    
    def _parse_field_names(self, response: str) -> list:
        """Parse model output to extract field names"""
        # Implementation needed
        pass
```

#### 6.2. Integration vào Backend

Update `backend/gemini_client.py`:

```python
from mail_merge_model_inference import MailMergeFieldPredictor

class FieldAnalyzer:
    def __init__(self):
        self.model = MailMergeFieldPredictor()
        # Fallback to Gemini if model fails
        self.gemini_client = GeminiClient()
    
    def analyze_field_context(self, text_segment: str) -> str:
        """Analyze context and suggest field name"""
        try:
            # Try local model first
            return self.model.predict_field_names(text_segment)
        except Exception as e:
            # Fallback to Gemini
            return self.gemini_client.generate_field_name(text_segment)
```

---

## 📊 Success Metrics & Evaluation

### Quantitative Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Accuracy** | >90% | Correct field naming on test set |
| **Inference Speed** | <1s | Time per document prediction |
| **Model Size** | <5GB | Merged model disk size |
| **Generalization** | >85% | Performance on unseen patterns |

### Qualitative Evaluation

Test cases:
1. **Basic forms**: Simple Vietnamese forms
2. **Government forms**: Complex bureaucratic forms  
3. **Corporate forms**: HR/Admin forms
4. **Edge cases**: Weird formatting, typos

### Benchmark against Gemini API

Compare fine-tuned model vs current Gemini implementation:
- Cost per inference
- Latency
- Accuracy on Vietnamese forms
- Consistency

---

## 🔧 Configuration Files Summary

### Files cần tạo

```
backend/LlamaFactory/
├── data/
│   ├── mail_merge_vi_train.json     # 145 examples
│   ├── mail_merge_vi_val.json       # 18 examples  
│   ├── mail_merge_vi_test.json      # 18 examples
│   └── dataset_info.json            # Update with mail_merge_vi entry
├── examples/
│   ├── mail_merge_lora_sft.yaml     # Training config
│   └── mail_merge_export.yaml       # Export config
└── saves/
    ├── mail_merge_qwen3_lora/       # LoRA checkpoints
    └── mail_merge_qwen3_merged/     # Final merged model
```

### Update dataset_info.json

```json
"mail_merge_vi": {
  "file_name": "mail_merge_vi_train.json",
  "formatting": "alpaca",
  "columns": {
    "prompt": "instruction",
    "query": "input",
    "response": "output"
  },
  "tags": {
    "role_tag": "instruction",
    "content_tag": "content",
    "user_tag": "input",
    "assistant_tag": "output"
  }
}
```

---

## 🚀 Quick Start Commands

### Development (Local)

```bash
# Setup
cd backend/LlamaFactory
pip install -e .
pip install -r requirements/metrics.txt

# Train (khó khăn trên Apple M4)
llamafactory-cli train examples/mail_merge_lora_sft.yaml

# Chat/Inference
llamafactory-cli chat examples/inference/mail_merge_chat.yaml

# Export model
llamafactory-cli export examples/mail_merge_export.yaml
```

### Production (Cloud)

```bash
# On Colab/RunPod with GPU
git clone https://github.com/hiyouga/LlamaFactory.git
cd LlamaFactory
pip install -e .

# Upload data files rồi train
llamafactory-cli train mail_merge_lora_sft.yaml

# Download model khi done
# File ở: saves/mail_merge_qwen3_lora/
```

---

## 📈 Timeline Gantt

```
Week 1:
| Day 1-2 | Environment Setup                  |
| Day 2-4 | Dataset Creation (170+ examples)   |
| Day 4   | Training Configuration              |

Week 2:
| Day 5-7 | Training Execution                  |
| Day 7   | Model Export                        |
| Day 8-10| Integration & Testing               |
```

---

## 💰 Cost Estimation

### Local Training
- **Cost**: $0 (miễn phí)
- **Time**: 20-30 hours (Apple M4 CPU)
- **VRAM**: N/A (CPU only)

### Cloud Training (Recommended)

**Google Colab Free**
- **Cost**: $0 (miễn phí)
- **Time**: 2-4 hours
- **Limit**: Daily usage limits

**RunPod/Vast.ai**
- **Cost**: $5-10 total
- **Time**: 1-2 hours
- **Hardware**: RTX 3090/4090

**Google Cloud Platform**
- **Cost**: $10-15 total (với free credit)
- **Time**: 1-2 hours
- **Hardware**: T4 GPU

---

## 🔄 Fallback Strategy

### Nếu fine-tune thất bại

1. **Reduce complexity**: 
   - Start với smaller dataset (50 examples)
   - Reduce lora_rank từ 16 → 8
   
2. **Use pretrained model**:
   - Qwen3-4B-Instruct mà không fine-tune
   - Hoặc use Gemini API như hiện tại

3. **Alternative approach**:
   - Rule-based field naming
   - Template matching thay vì ML

### Nếu integration thất bại

1. **Keep both systems**: 
   - Fine-tuned model as primary
   - Gemini as fallback
   
2. **A/B testing**:
   - Compare accuracy giữa 2 systems
   - Route complex forms đến Gemini

---

## 📚 Resources & References

### LlamaFactory Documentation
- **Main Docs**: https://llamafactory.readthedocs.io/
- **GitHub**: https://github.com/hiyouga/LlamaFactory
- **Examples**: `backend/LlamaFactory/examples/`

### Dataset Creation
- **Alpaca format**: https://github.com/tatsu-lab/stanford_alpaca
- **Vietnamese NLP**: https://github.com/HUST-Vilab/ViSpec

### Model Resources
- **Qwen3**: https://huggingface.co/Qwen/Qwen3-4B-Instruct
- **Unsloth Guide**: https://unsloth.ai/docs/

### Cloud Platforms
- **Google Colab**: https://colab.research.google.com/
- **RunPod**: https://www.runpod.io/
- **Vast.ai**: https://vast.ai/

---

## ✅ Checklist

### Pre-training
- [ ] Install LlamaFactory dependencies
- [ ] Create dataset files (170+ examples)
- [ ] Update dataset_info.json
- [ ] Create training config YAML
- [ ] Test data loading

### Training
- [ ] Setup cloud GPU (Colab/RunPod)
- [ ] Upload training files
- [ ] Start training job
- [ ] Monitor loss curve
- [ ] Save best checkpoint

### Post-training
- [ ] Export merged model
- [ ] Test inference speed
- [ ] Evaluate on test set
- [ ] Compare vs Gemini baseline

### Integration
- [ ] Create inference wrapper
- [ ] Update backend code
- [ ] Test with real documents
- [ ] Deploy to production
- [ ] Monitor performance

---

## 🎓 Learning Outcomes

Sau khi hoàn thành plan này, bạn sẽ:

1. ✅ **Hiểu fine-tuning workflow**: Từ data → train → deploy
2. ✅ **Expertise in LlamaFactory**: One of the most popular LLM fine-tuning frameworks
3. ✅ **Vietnamese NLP experience**: Specific challenges cho tiếng Việt
4. ✅ **Production integration**: How to integrate fine-tuned models vào real systems
5. ✅ **Cost optimization**: Cloud vs local training strategies

---

## 🆘 Support & Troubleshooting

### Common Issues

**1. Out of Memory (OOM)**
```yaml
# Reduce batch size
per_device_train_batch_size: 1
gradient_accumulation_steps: 16

# Enable gradient checkpointing
gradient_checkpointing: true
```

**2. Training Loss Not Decreasing**
```yaml
# Lower learning rate
learning_rate: 1.0e-5

# Increase warmup
warmup_ratio: 0.2

# More epochs
num_train_epochs: 10.0
```

**3. Poor Inference Results**
- Check data quality
- Increase training examples
- Try different lora_rank values
- Consider larger base model

### Get Help

- **LlamaFactory Issues**: https://github.com/hiyouga/LlamaFactory/issues
- **LLM Fine-tuning Discord**: Various communities
- **Stack Overflow**: Tag with `llama-factory`, `qwen`, `lora`

---

## 📝 Notes

- **Date Created**: 2025-06-08
- **Author**: AI Assistant (Claude)
- **Version**: 1.0
- **Status**: Ready for Implementation

---

**🎯 Next Steps**: Choose Option 1 (Local) hoặc Option 2 (Cloud) và bắt đầu implementation!