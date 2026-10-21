set -e
cp agent.py agent.fixed; cp tools.py tools.fixed
trap 'cp agent.fixed agent.py; cp tools.fixed tools.py' EXIT
cp agent.py.bak agent.py; cp tools.py.bak tools.py
python3 bench.py before_final 5
cp agent.fixed agent.py; cp tools.fixed tools.py
python3 bench.py after_final 5
