import sys

if __name__ == "__main__":
    if "--desktop" in sys.argv:
        sys.argv.remove("--desktop")
        from echoscope.presentation.desktop import main
    else:
        from echoscope.presentation.web import main

    main()
