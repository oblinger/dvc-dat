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

## Ask
- How to: from ml_dat import Inst, do
- Accept list into a constructor.  must I do a shallow copy?
- Should .add_insts accept a list of insts or a star list of insts?
- I plan to split ml-cube from ml-dat
- Right now Inst has ALL property functions.  maybe it is more confusing than helpful.  

## Todo
- [ ] convert inst names to use '.' instead of '/'

## Later
- [ ] Split ml-cube into a separate package
- [ ] Add a `requirements.txt` file
- [ ] Add a `setup.py` file
- [ ] make inst use the datconfig defined folder 
- Support cube of cubes with cached points in sub cubes
TODO for cube.py
- Implement the 'merge_keys' method
- Implement the 'get_csv' method
- Support inst 'Cube' section that build data cube and cube reports
