"""
Test script for Batch Update API

Tests various operation types to ensure the batch update endpoint works correctly.
Run this after starting the backend server: `uvicorn main:app --reload`
"""

import requests
import json

API_BASE = "http://localhost:8000"

def test_batch_update():
    """Test batch update with multiple operations"""

    # Test 1: Placeholder operations (rename, delete)
    operations_1 = [
        {"type": "rename_placeholder", "old_name": "ngay", "new_name": "ngay_sinh"},
        {"type": "delete_placeholder", "field_name": "cap_duong_nuoi_con"}
    ]

    try:
        response = requests.post(
            f"{API_BASE}/batch-update",
            json={
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "operations": operations_1,
                "validate_only": False,
                "stop_on_error": True
            },
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            print("✓ Test 1 PASSED")
            print(f"  Total: {result['total_operations']}, Successful: {result['successful']}, Failed: {result['failed']}")
        else:
            print(f"✗ Test 1 FAILED: {response.status_code}")
    except Exception as e:
        print(f"✗ Test 1 EXCEPTION: {str(e)}")

    # Test 2: Mixed operations (text + formatting)
    operations_2 = [
        {
            "type": "update_text",
            "block_index": 15,
            "old_text": "Tôi xin yêu cầu",
            "new_text": "Tôi xin kính yêu cầu"
        },
        {
            "type": "format_text",
            "block_index": 38,
            "selected_text": "Hướng dẫn viết đơn:",
            "format_config": {"bold": True, "underline": True, "color": "0000FF"}
        }
    ]

    try:
        response = requests.post(
            f"{API_BASE}/batch-update",
            json={
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "operations": operations_2,
                "validate_only": False,
                "stop_on_error": True
            },
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            result = response.json()
            print("✓ Test 2 PASSED")
            print(f"  Successful: {result['successful']}")
        else:
            print(f"✗ Test 2 FAILED: {response.status_code}")
    except Exception as e:
        print(f"✗ Test 2 EXCEPTION: {str(e)}")

    # Test 3: Validate only mode
    operations_3 = [
        {"type": "add_placeholder", "block_index": 10, "field_name": "test_placeholder", "position": "right"}
    ]

    try:
        response = requests.post(
            f"{API_BASE}/batch-update",
            json={
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "operations": operations_3,
                "validate_only": True,
                "stop_on_error": True
            },
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            print("✓ Test 3 PASSED (validate only)")
        else:
            print(f"✗ Test 3 FAILED: {response.status_code}")
    except Exception as e:
        print(f"✗ Test 3 EXCEPTION: {str(e)}")

    # Test 4: Error handling (invalid block_index)
    operations_4 = [
        {"type": "update_text", "block_index": 9999, "old_text": "test", "new_text": "test"}
    ]

    try:
        response = requests.post(
            f"{API_BASE}/batch-update",
            json={
                "template_id": "778c04c8-d477-49ff-a791-274bc4ee9a9e",
                "operations": operations_4,
                "validate_only": False,
                "stop_on_error": True
            },
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 400:
            print("✓ Test 4 PASSED (validation failed as expected)")
        else:
            print(f"? Test 4 UNEXPECTED: {response.status_code}")
    except Exception as e:
        print(f"✗ Test 4 EXCEPTION: {str(e)}")


if __name__ == "__main__":
    test_batch_update()
