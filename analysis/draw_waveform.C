// 사용법: ./draw_waveform <RunNo> <evt> <channel> [channel ...] [-g]

#include "../include/DQMDraw.h"

#include <TH1F.h>

void draw_waveform(int RunNo, const char* channels, long long evt = 0,
                   const char* inPath = kDQMDefaultPath)
{
	DQM_FillAndDraw<TH1F>(RunNo, channels, evt, 1, inPath, Form("waveform_evt%lld", evt), "Waveform",
		"HIST", false, false,
		[evt](const TString& hname, const TString& label, const ChannelWaveform& w, const DAQInfo&) {
			const int ns = (int)w.adc.size();
			TH1F* h = new TH1F(hname, label + Form(", event %lld;sample;ADC", evt), ns, 0, ns);
			h->SetDirectory(nullptr);
			h->SetStats(0);
			for (int i = 0; i < ns; ++i) h->SetBinContent(i + 1, w.adc[i]);
			return h;
		},
		[](TH1F*, const ChannelWaveform&, const DAQInfo&, long long) {});
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(3, "./draw_waveform <RunNo> <evt> <channel> [channel ...] [-g]")) return 1;
	const auto& a = app.Args();
	draw_waveform(std::stoi(a[0]), DQM_JoinArgs(a, 2).c_str(), std::stoll(a[1]), DQM_DataPath());
	return app.Run();
}
#endif
