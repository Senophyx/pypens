class APIError(Exception):
    def __init__(self, msg:str='An error occurred within the API'):
        super().__init__(str(msg))