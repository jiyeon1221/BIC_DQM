#ifndef DQM_APP_H
#define DQM_APP_H

#include <TApplication.h>
#include <TCanvas.h>
#include <TROOT.h>
#include <TRootCanvas.h>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

inline const char* DQM_DataPath()
{
	const char* p = std::getenv("DQM_DATA_PATH");
	return (p && *p) ? p : "/home/kobic/26CERNData/binary";
}

class DQMApp {
public:
	DQMApp(int argc, char** argv)
	{
		bool batch = true;
		for (int i = 1; i < argc; ++i) {
			if (!std::strcmp(argv[i], "-g")) batch = false;
			else if (std::strcmp(argv[i], "-b")) fArgs.push_back(argv[i]);
		}
		if (!batch && !std::getenv("DISPLAY")) {
			std::cerr << "[DQM] no DISPLAY, saving only\n";
			batch = true;
		}
		gROOT->SetBatch(batch);
		if (!batch) {
			static int appArgc = 1;
			fApp = new TApplication("DQM", &appArgc, argv);
		}
	}

	const std::vector<std::string>& Args() const { return fArgs; }

	bool Need(size_t n, const char* usage) const
	{
		if (fArgs.size() >= n) return true;
		std::cerr << "usage: " << usage << "\n";
		return false;
	}

	int Run()
	{
		if (!fApp) return 0;
		bool any = false;
		for (TObject* o : *gROOT->GetListOfCanvases()) {
			auto* rc = dynamic_cast<TRootCanvas*>(static_cast<TCanvas*>(o)->GetCanvasImp());
			if (!rc) continue;
			rc->Connect("CloseWindow()", "TApplication", fApp, "Terminate()");
			any = true;
		}
		if (any) {
			std::cout << "[DQM] close any canvas window to quit\n";
			fApp->Run();
		}
		return 0;
	}

private:
	std::vector<std::string> fArgs;
	TApplication*            fApp = nullptr;
};

inline std::string DQM_JoinArgs(const std::vector<std::string>& args, size_t first)
{
	std::string s;
	for (size_t i = first; i < args.size(); ++i) s += (s.empty() ? "" : " ") + args[i];
	return s;
}

#endif
