"""Finite, non-sensitive local maintenance errors; no provider dependency."""


class ConversationError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)
