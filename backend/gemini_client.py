"""
Simple Gemini Client for text extraction (no code generation)
Used only in /merge endpoint to extract structured data from context
"""
import json
import google.generativeai as genai


class GeminiClient:
    """Simple client for Gemini API - text extraction only"""

    def __init__(self, api_key: str):
        """Initialize Gemini client

        Args:
            api_key: Gemini API key
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('models/gemini-3.1-flash-lite-preview')
