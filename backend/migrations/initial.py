from src.config.database import Base, engine
from src import models


def migrate():
    Base.metadata.create_all(engine)
    from src.migrations.reviews import run
    run()


if __name__ == '__main__':
    migrate()
