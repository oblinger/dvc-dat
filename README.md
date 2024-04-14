# dat
Data and code encapsulation for ML experimentation and productization


## Installation

```bash
pip install -e .
```

## Usage

```bash
cd tests; ./do hello_world
```

## Testing

```bash
python -m pytest
```

## Development

```bash
python -m black src
```


## Todo
- [ ] Split ml-cube into a separate package
- [ ] Add a `requirements.txt` file
- [ ] Add a `setup.py` file
- [ ] make inst use the datconfig defined folder 
TODO for cube.py
- Add basic readme
- Implement the 'merge_keys' method
- Implement the 'get_csv' method
- Support inst 'Cube' section that build data cube and cube reports
- Support cube of cubes with cached points in sub cubes
