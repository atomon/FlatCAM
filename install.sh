#!/bin/bash

pyenv install 3.11.6
pyenv local 3.11.6

python -m venv .venv
sudo chmod 555 .venv/bin/activate
. .venv/bin/activate 

python -m pip install -r requirements.txt
