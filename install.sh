#!/bin/bash

pyenv install 3.11.6
pyenv local 3.11.6

python -m venv .venv

python -m pip install -r requirements.txt
