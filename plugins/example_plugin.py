"""
QUICK Example Plugin
Demonstrates how to dynamically add new tools to QUICK.
"""
import re

def initialize(register_tool):
    """
    Called by QUICK on startup.
    register_tool(tool_name: str, regex_trigger: re.Pattern, handler: callable)
    """
    # Trigger on the word "greet" or "hello plugin"
    trigger = re.compile(r'\b(greet|hello plugin)\b', re.IGNORECASE)
    
    def handle_greet(user_text):
        return "PLUGIN EXECUTED: Hello from the QUICK Custom Plugin architecture! Your environment is highly extensible."
    
    # Register the tool
    register_tool('example_greet', trigger, handle_greet)
    print("[Plugins] Registered tool: example_greet")
