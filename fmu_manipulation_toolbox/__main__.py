import sys


def gui():
    try:
        from .gui import main
        main()
    except ModuleNotFoundError as e:
        print(f"FATAL ERROR: {e}. No GUI Available.")


def cli():
    from .cli.fmutool import fmutool
    fmutool()


def main():
    if len(sys.argv) == 1:
        gui()
    else:
        cli()


if __name__ == '__main__':
    main()
