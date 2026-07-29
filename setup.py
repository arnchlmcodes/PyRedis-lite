from setuptools import setup, find_packages

setup(
    name="pyredis-lite",
    version="0.1.0",
    packages=find_packages(exclude=["tests*"]),
    entry_points={
        "console_scripts": [
            "pyredis-lite=redis_clone.server:main",
        ],
    },
    extras_require={
        "dev": [
            "redis>=5.0,<6.0",
            "pytest>=8.0,<9.0",
            "pytest-timeout>=2.3,<3.0",
        ],
    },
)

