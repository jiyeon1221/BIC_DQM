#ifndef READER_NKFADC_H
#define READER_NKFADC_H

#include "DAQReader.h"

class NKFADCReader : public DAQReader {
public:
	static constexpr int    nCh      = 4;
	static constexpr double sampleNs = 2.0;

	const DAQInfo& Info() const override
	{
		static const DAQInfo info{"NKFADC", {1, 2, 3, 4},
		                          -1, 30, 0, -1, true, false,
		                          0, {4096, -0.5, 4095.5}, {0, -200, 12000},
		                          {600, 0, 600}, {200, -1000, 1000},
		                          0, 4095};
		return info;
	}

	bool Open(const char* inPath, int RunNo, int mid) override
	{
		if (!OpenFile(Form("%s/Run_%05d_FADC_%d.dat", inPath, RunNo, mid), mid)) return false;

		unsigned char first[4 * nCh];
		if (fread(first, 1, sizeof(first), fFile) != sizeof(first)) {
			std::cerr << "[DAQ] " << fName << " is empty\n";
			Close();
			return false;
		}
		rewind(fFile);

		fDLen = 0;
		for (int lane = 0; lane < nCh && (fDLen <= 32 || fDLen > 16384); ++lane) {
			fDLen = 0;
			for (int b = 0; b < 4; ++b) fDLen |= (int)first[lane + nCh * b] << (8 * b);
		}
		if (fDLen <= 32 || fDLen > 16384) {
			std::cerr << "[DAQ] " << fName << ": invalid block length " << fDLen << "\n";
			Close();
			return false;
		}
		fRaw.assign(nCh * fDLen, 0);
		return true;
	}

	bool Next(std::vector<ChannelWaveform>& out) override
	{
		out.clear();
		if (!fFile) return false;
		if (fread(fRaw.data(), 1, fRaw.size(), fFile) != fRaw.size()) return false;

		const int nADC = NSamples();
		for (int ch = 0; ch < nCh; ++ch) {
			int dlen = 0;
			for (int b = 0; b < 4; ++b) dlen |= (int)Byte(ch, b) << (8 * b);
			if (dlen != fDLen || Byte(ch, 15) != fMid || Byte(ch, 16) != ch + 1) {
				if (fNBad++ < 10)
					std::cerr << "[DAQ] " << fName << ": lane " << ch << " bad header (length " << dlen
					          << ", MID " << (int)Byte(ch, 15) << ", channel " << (int)Byte(ch, 16)
					          << "), channel skipped\n";
				continue;
			}
			out.emplace_back();
			ChannelWaveform& w = out.back();
			w.mid = fMid;
			w.ch  = Byte(ch, 16);
			unsigned char trig[4] = {Byte(ch, 7), Byte(ch, 8), Byte(ch, 9), Byte(ch, 10)};
			w.trigger = DAQ_LittleEndian(trig, 4);
			w.adc.resize(nADC);
			for (int s = 0; s < nADC; ++s) {
				const int idx = 32 + 2 * s;
				w.adc[s] = (Byte(ch, idx) & 0xFF) | ((Byte(ch, idx + 1) & 0x0F) << 8);
			}
		}
		return true;
	}

	int DLen() const { return fDLen; }
	int NSamples() const { return (fDLen - 32) / 2; }

private:
	unsigned char Byte(int ch, int k) const { return fRaw[ch + nCh * k]; }

	int fDLen = 0;
	std::vector<unsigned char> fRaw;
};

#endif
