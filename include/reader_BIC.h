#ifndef READER_BIC_H
#define READER_BIC_H

#include "DAQReader.h"

class BICReader : public PacketReader {
public:
	const DAQInfo& Info() const override
	{
		static const DAQInfo info{"BIC", {41, 42, 43},
		                          +1, 0, 10, 60, false, true,
		                          120, {2000, -4000, 20000}, {0, -4000, 12000},
		                          {10000, 0, 10000}, {1000, -100, 70000},
		                          -32768, 32767};
		return info;
	}
	bool Open(const char* inPath, int RunNo, int mid) override
	{
		return OpenFile(Form("%s/Run_%05d_BIC_%d.dat", inPath, RunNo, mid), mid);
	}

protected:
	int SampleStride() const override { return 4; }
};

#endif
