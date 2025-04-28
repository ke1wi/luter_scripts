class DatabaseException(Exception):
    def __init__(self, message="An error occurred in the database", *args):
        super().__init__(message, *args)
