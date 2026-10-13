// 사용법: ./draw_intADC <RunNo> <nEvt> <channel> [channel ...] [-g]

#include "../include/DQMDraw.h"

#include <TH1F.h>

void draw_intADC(int RunNo, const char* channels, long long nEvt = -1,
                 const char* inPath = kDQMDefaultPath)
{
	DQM_FillAndDraw<TH1F>(RunNo, channels, 0, nEvt, inPath, "intADC", "IntADC", "HIST", true, false,
		[](const TString& hname, const TString& label, const ChannelWaveform&, const DAQInfo& info) {
			TH1F* h = new TH1F(hname, label + ";integral ADC;events", info.integral.nBins, info.integral.min, info.integral.max);
			h->SetDirectory(nullptr);
			return h;
		},
		[](TH1F* h, const ChannelWaveform& w, const DAQInfo& info, long long) {
			const PulseSummary s = SummarizePulse(w.adc, info);
			if (s.valid) h->Fill(s.integral);
		});
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(3, "./draw_intADC <RunNo> <nEvt> <channel> [channel ...] [-g]")) return 1;
	const auto& a = app.Args();
	draw_intADC(std::stoi(a[0]), DQM_JoinArgs(a, 2).c_str(), std::stoll(a[1]), DQM_DataPath());
	return app.Run();
}
#endif
