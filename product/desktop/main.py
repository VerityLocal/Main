"""Entry point, including frozen multiprocessing dispatch before Tk is imported."""
import multiprocessing


def main():
    multiprocessing.freeze_support()
    import argparse
    parser = argparse.ArgumentParser(description="Verity native desktop application")
    parser.add_argument("--acceptance-output", help="Developer-only functional GUI acceptance; choose a new output folder")
    args = parser.parse_args()
    from .config import bundle_root, offline_policy
    root = bundle_root()
    offline_policy(root)
    from .app import DesktopApp
    app = DesktopApp(root)
    if args.acceptance_output:
        from .acceptance import Acceptance
        Acceptance(app, args.acceptance_output)
    app.mainloop()


if __name__ == "__main__":
    main()
