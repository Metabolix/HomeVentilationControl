# Rename to main.py, or simply import HomeVentilationWebMain

from WebMain import WebMain
class HomeVentilationWebMain(WebMain):
    def __init__(self):
        from SimpleWLAN import SimpleWLAN
        from WebFileManager import WebFileManager

        network = SimpleWLAN.from_config()
        super().__init__(network)

        self.add_static("/HomeVentilationWebMain.ico", "/favicon.ico")
        self.add_module(WebFileManager())

        try:
            from HomeVentilationControl import HomeVentilationControl
            self.add_module(HomeVentilationControl())
        except BaseException as e:
            self._log(e)

HomeVentilationWebMain.main()
