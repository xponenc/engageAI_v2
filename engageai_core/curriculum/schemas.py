TASK_CONTENT_SCHEMAS = {
    "mcq_v1": {
        "required": {"prompt", "options", "correct_idx"},
        "optional": {"explanation"},
        "options_type": "list[str]"
    },
    "mcq_v2": {
        "required": {"prompt", "options", "correct_ids"},
        "options_type": "list[dict]",
        "option_required": {"text"}
    },
    "short_text_v1": {
        "required": {"prompt", "correct"},
        "correct_type": "list[str]"
    }
}