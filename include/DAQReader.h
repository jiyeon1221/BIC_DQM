#ifndef DAQ_READER_H
#define DAQ_READER_H

#include <TString.h>

#include <algorithm>
#include <cstdio>
#include <iostream>
#include <memory>
#include <vector>

struct ChannelWaveform {
	int mid = 0;
	int ch = 0;
	unsigned int trigger = 0;
	std::vector<double> adc;
};

struct HistAxis {
	int    nBins;
	double min;
	double max;
};

struct DAQInfo {
	const char*      name;
	std::vector<int> mids;

	int  polarity;
	int  nPed;
	int  sumFirst;
	int  sumLast;
	bool peakFromZero;
	bool skipAllZero;

	int      overlayXBins;
	HistAxis overlayY;
	HistAxis avgY;
	HistAxis peak;
	HistAxis integral;

	double adcMin;
	double adcMax;
};

inline unsigned int DAQ_LittleEndian(const unsigned char* p, int nBytes)
{
	unsigned int v = 0;
	for (int i = 0; i < nBytes; ++i) v |= (unsigned int)p[i] << (8 * i);
	return v;
}

class DAQReader {
public:
	virtual ~DAQReader() { Close(); }
	virtual const DAQInfo& Info() const = 0;
	virtual bool Open(const char* inPath, int RunNo, int mid) = 0;

	virtual bool Next(std::vector<ChannelWaveform>& out) = 0;

	void Close()
	{
		if (fFile) fclose(fFile);
		fFile = nullptr;
	}
	const TString& FileName() const { return fName; }
	long long NBad() const { return fNBad; }

protected:
	bool OpenFile(const TString& name, int mid)
	{
		Close();
		fName = name;
		fMid  = mid;
		fNBad = 0;
		fFile = fopen(fName.Data(), "rb");
		if (!fFile) {
			std::cerr << "[DAQ] cannot open " << fName << std::endl;
			return false;
		}
		return true;
	}

	FILE*     fFile = nullptr;
	TString   fName;
	int       fMid  = 0;
	long long fNBad = 0;
};

class PacketReader : public DAQReader {
public:
	bool Next(std::vector<ChannelWaveform>& out) override
	{
		out.clear();
		if (!fFile) return false;
		unsigned char hdr[32];
		while (true) {
			const long pos = ftell(fFile);
			if (fread(hdr, 1, 32, fFile) != 32) return false;
			const int len = (int)DAQ_LittleEndian(hdr, 4);
			if (len <= 32 || len > kMaxPacket) {
				if (fNBad++ < 10)
					std::cerr << "[DAQ] " << fName << ": bad packet length " << len
					          << " at byte " << pos << ", resyncing\n";
				fseek(fFile, pos + 1, SEEK_SET);
				continue;
			}
			fBody.resize(len - 32);
			if (fread(fBody.data(), 1, fBody.size(), fFile) != fBody.size()) return false;

			ChannelWaveform w;
			w.mid     = fMid;
			w.ch      = hdr[16];
			w.trigger = DAQ_LittleEndian(hdr + 7, 4);
			const int stride = SampleStride();
			const int n = (int)fBody.size() / stride;
			w.adc.resize(n);
			for (int i = 0; i < n; ++i)
				w.adc[i] = (short)(fBody[stride * i] | (fBody[stride * i + 1] << 8));
			out.push_back(std::move(w));
			return true;
		}
	}

protected:

	virtual int SampleStride() const = 0;

	static constexpr int kMaxPacket = 65536;
	std::vector<unsigned char> fBody;
};

struct PulseSummary {
	bool   valid    = false;
	double ped      = 0;
	double peak     = 0;
	double integral = 0;
};

inline bool DAQ_IsAllZero(const std::vector<double>& adc)
{
	return std::all_of(adc.begin(), adc.end(), [](double a) { return a == 0; });
}

inline PulseSummary SummarizePulse(const std::vector<double>& adc, const DAQInfo& info)
{
	PulseSummary s;
	const int n = (int)adc.size();

	const int nPed = std::min(info.nPed, n);
	if (nPed > 0) {
		for (int i = 0; i < nPed; ++i) s.ped += adc[i];
		s.ped /= nPed;
	}

	const int first = std::max(info.sumFirst, 0);
	const int last  = info.sumLast < 0 ? n : std::min(info.sumLast, n);
	if (last <= first) return s;

	s.valid = true;
	s.peak  = info.peakFromZero ? 0 : -1e300;
	for (int i = first; i < last; ++i) {
		const double v = nPed > 0 ? info.polarity * (adc[i] - s.ped) : info.polarity * adc[i];
		s.integral += v;
		if (v > s.peak) s.peak = v;
	}
	return s;
}

#endif
