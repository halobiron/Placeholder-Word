#!/usr/bin/env python3
"""
Test fine-tuned model integration
"""
import os
import sys
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

def test_finetuned_client():
    """Test GeminiClient with finetuned provider"""
    print("=== Testing Fine-tuned Model Integration ===\n")

    # Load config from .env
    provider = os.getenv("AI_PROVIDER", "gemini")
    finetuned_path = os.getenv("FINETUNED_PATH")
    finetuned_base_model = os.getenv("FINETUNED_BASE_MODEL")

    print(f"Provider: {provider}")
    print(f"Fine-tuned path: {finetuned_path}")
    print(f"Base model: {finetuned_base_model}\n")

    if provider != "finetuned":
        print("❌ AI_PROVIDER must be set to 'finetuned' in .env")
        return False

    if not finetuned_path or not finetuned_base_model:
        print("❌ FINETUNED_PATH and FINETUNED_BASE_MODEL must be set in .env")
        return False

    # Check if path exists
    if not Path(finetuned_path).exists():
        print(f"❌ Fine-tuned path does not exist: {finetuned_path}")
        return False

    try:
        from gemini_client import GeminiClient

        print("✅ GeminiClient import successful\n")

        # Initialize client
        print("Initializing fine-tuned client...")
        client = GeminiClient(
            api_key=os.getenv("GEMINI_API_KEY"),
            provider=provider,
            finetuned_path=finetuned_path,
            finetuned_base_model=finetuned_base_model,
        )
        print("✅ Fine-tuned model loaded successfully!\n")

        # Test simple generation
        print("Testing text generation...")
        test_prompt = "Trích xuất thông tin từ đoạn văn sau: Nguyễn Văn A, sinh năm 1990, quê quán Hà Nội."

        response = client.generate_content(test_prompt)

        print(f"✅ Generation successful!\n")
        print(f"Response: {response.text[:200]}...")
        print(f"\nToken usage: {response.usage_metadata}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_finetuned_client()
    sys.exit(0 if success else 1)
