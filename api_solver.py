#!/usr/bin/env python3
"""
Turnstile solver entry point. Delegates to solver.server.
This file is launched as a subprocess by run.py.
"""
if __name__ == "__main__":
    from solver.server import main
    main()
