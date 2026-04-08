from setuptools import setup, find_packages

setup(
    name="subcal",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.111.0",
        "uvicorn[standard]>=0.29.0",
        "python-multipart>=0.0.9",
    ],
    entry_points={
        "console_scripts": [
            "subcal=subcal.__main__:main",
        ],
    },
    python_requires=">=3.6",
)
