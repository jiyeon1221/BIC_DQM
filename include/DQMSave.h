#ifndef DQM_SAVE_H
#define DQM_SAVE_H

#include <TCanvas.h>
#include <TDirectory.h>
#include <TFile.h>
#include <TH1.h>
#include <TString.h>
#include <TSystem.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <vector>

#include <unistd.h>

inline TString DQM_OutputDir()
{
	const char* env = std::getenv("DQM_OUTPUT_PATH");
	if (env && *env) return env;

	const TString header = __FILE__;
	char top[4096];
	if (header.BeginsWith("/") && realpath(gSystem->GetDirName(header) + "/..", top)) return TString(top) + "/output";

	char exe[4096];
	const ssize_t n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
	if (n > 0) {
		exe[n] = '\0';
		return gSystem->GetDirName(gSystem->GetDirName(exe)) + "/output";
	}
	return "./output";
}

inline TString DQM_OutputPath(const char* dir, int RunNo, const TString& base)
{
	const TString path = Form("%s/%s/Run_%d", DQM_OutputDir().Data(), dir, RunNo);
	gSystem->mkdir(path, kTRUE);
	return path + "/" + base + ".root";
}

inline TString DQM_FileTag(const char* selector)
{
	TString out;
	bool sep = false;
	for (const char* p = selector; *p; ++p) {
		const char c = *p;
		if (std::isalnum((unsigned char)c) || c == '-' || c == '+') {
			if (sep && out.Length()) out += "_";
			sep = false;
			out += c;
		} else if (c == '*') {
			out += "all";
		} else if (c == '?') {
			out += "X";
		} else if (c == ':') {
			out += "-";
		} else {
			sep = true;
		}
	}
	return out;
}

inline void DQM_CollectHists(TVirtualPad* pad, std::vector<TH1*>& out)
{
	for (TObject* o : *pad->GetListOfPrimitives()) {
		if (o->InheritsFrom(TVirtualPad::Class())) DQM_CollectHists(static_cast<TVirtualPad*>(o), out);
		else if (o->InheritsFrom(TH1::Class()) && std::find(out.begin(), out.end(), o) == out.end())
			out.push_back(static_cast<TH1*>(o));
	}
}

inline void DQM_SaveCanvases(const std::vector<TCanvas*>& canvases, const TString& fileName)
{
	TDirectory* prev = gDirectory;
	TFile* f = TFile::Open(fileName, "RECREATE");
	if (!f || f->IsZombie()) {
		std::cerr << "[DQM] cannot write " << fileName << "\n";
		if (prev) prev->cd();
		return;
	}
	for (TCanvas* c : canvases) {
		if (!c) continue;
		f->cd();
		c->Write();
		std::vector<TH1*> hists;
		DQM_CollectHists(c, hists);
		TDirectory* d = f->mkdir(Form("%s_hists", c->GetName()));
		if (!d) continue;
		d->cd();
		for (TH1* h : hists) h->Write();
	}
	f->Close();
	delete f;
	if (prev) prev->cd();
	std::cout << "[DQM] saved " << fileName << "\n";
}

#endif
