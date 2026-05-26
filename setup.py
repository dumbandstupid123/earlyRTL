from setuptools import setup, find_packages

setup(
    name="rtlsense",
    version="0.1.0",
    author="Sandeep Ramlochan",
    description="Real-time timing analysis linter for Verilog",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "click>=8.0",
        "rich>=13.0",
        "watchdog>=3.0",
        "anthropic>=0.25.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "rtlsense=rtlsense.cli:rtlsense",
        ],
    },
)
