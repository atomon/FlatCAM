if ($env:VIRTUAL_ENV)
{
    deactivate
}

# extract python major version
$python_v = $(python -V)
$first_index = ${python_v}.IndexOf(".")
$last_index = ${python_v}.LastIndexOf(".")
$python_major_v = ${python_v}.Substring(${first_index} + 1, ${last_index} - ${first_index} - 1)

# Install and Set Python
if (${python_major_v} -ne "11")
{
    pyenv install 3.11.6
    pyenv local 3.11.6
}

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install required packages
python -m pip install -r requirements.txt
pip install pywin32==306

deactivate
