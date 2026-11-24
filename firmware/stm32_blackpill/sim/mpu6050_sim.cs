//
// scripted MPU6050 for the Black Pill emulation.  a register model on the I2C bus: it has WHO_AM_I,
// PWR_MGMT_1, CONFIG, GYRO_CONFIG, ACCEL_CONFIG and the accelerometer data registers, with the register
// pointer incrementing on reads as in the data sheet.  the harness drives it through the public methods.
//
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;

namespace Antmicro.Renode.Peripherals.Sensors
{
    public class MpuSim : II2CPeripheral
    {
        // controller is the I2C peripheral this sensor sits on.  the harness uses it to unplug and plug the
        // sensor, which is the only way to make a device stop answering on this bus model.
        public MpuSim(IMachine machine, Antmicro.Renode.Peripherals.I2C.STM32F1_I2C controller)
        {
            this.controller = controller;
            this.machine = machine;
            Reset();
        }

        public void Reset()
        {
            for(int i = 0; i < regs.Length; i++) regs[i] = 0;
            regs[0x75] = whoAmI;
            regs[0x6B] = 0x40;          // power-up: asleep
            pointer = 0;
            nReads = 0;
            for(int i = 0; i < latched.Length; i++) latched[i] = 0;     // power-up: the data registers read zero
        }

        // ---- bus side ----
        public void Write(byte[] data)
        {
            if(data == null || data.Length == 0) return;
            writes++;
            pointer = data[0];
            for(int i = 1; i < data.Length; i++)
            {
                WriteReg(pointer, data[i]);
                pointer = (byte)(pointer + 1);
            }
        }

        public byte[] Read(int count = 1)
        {
            var res = new byte[count];
            for(int i = 0; i < count; i++)
            {
                res[i] = ReadReg(pointer);
                pointer = (byte)(pointer + 1);
            }
            return res;
        }

        public void FinishTransmission()
        {
        }

        private void WriteReg(byte reg, byte value)
        {
            if(reg == 0x75) return;     // read only
            regs[reg] = value;
        }

        private byte ReadReg(byte reg)
        {
            if(reg >= 0x3B && reg <= 0x40)
            {
                // the whole axis block is latched when X high is read, like the real part
                if(reg == 0x3B) LatchSample();
                return latched[reg - 0x3B];
            }
            if(reg == 0x75) return whoAmI;
            return regs[reg];
        }

        // sleeping part: it keeps returning the last latched sample, which is what makes it look stuck
        private void LatchSample()
        {
            if((regs[0x6B] & 0x40) != 0) return;
            nReads++;
            RecordGap();
            short x, y, z;
            if(frozen) { x = frozenX; y = frozenY; z = frozenZ; }
            else
            {
                double t = (double)sampleIndex / 100.0;
                x = Clamp(offX + ampX * Math.Sin(2 * Math.PI * freqHz * t));
                y = Clamp(offY + ampY * Math.Sin(2 * Math.PI * freqHz * t));
                z = Clamp(offZ + ampZ * Math.Sin(2 * Math.PI * freqHz * t));
                frozenX = x; frozenY = y; frozenZ = z;
            }
            bool periodic = (runEvery > 0 && (nReads % runEvery) < runLen) || (zeroEvery > 0 && (nReads % zeroEvery) == 0) || (zeroPercent > 0 && rng.Next(100) < zeroPercent);
            bool failing = allZero || zeroLeft > 0 || periodic;
            if(!frozen && !failing) sampleIndex++;     // a failed read does not use up a sample, so a retry sees the same one
            if(allZero || zeroLeft > 0 || periodic) { x = 0; y = 0; z = 0; }
            if(zeroLeft > 0) zeroLeft--;
            latched[0] = (byte)(((ushort)x) >> 8); latched[1] = (byte)x;
            latched[2] = (byte)(((ushort)y) >> 8); latched[3] = (byte)y;
            latched[4] = (byte)(((ushort)z) >> 8); latched[5] = (byte)z;
        }

        private static short Clamp(double v)
        {
            v = Math.Round(v);
            if(v > 32767) v = 32767;
            if(v < -32768) v = -32768;
            return (short)v;
        }

        // time between consecutive sample reads, in simulated microseconds.  a blocking line transmit or a
        // slow pass shows up as a gap well over 10 ms
        private void RecordGap()
        {
            long now = (long)machine.LocalTimeSource.ElapsedVirtualTime.TotalMicroseconds;
            if(lastReadUs >= 0)
            {
                long gap = now - lastReadUs;
                if(gap > maxGapUs) maxGapUs = gap;
                if(gap < minGapUs) minGapUs = gap;
                if(gap > 11000) gapsOver++;
                if(gap < 9000) gapsUnder++;
                gapN++;
            }
            lastReadUs = now;
        }

        // ---- harness controls (called from the Renode monitor) ----
        public void ResetGaps() { lastReadUs = -1; maxGapUs = 0; minGapUs = long.MaxValue; gapsOver = 0; gapsUnder = 0; gapN = 0; }
        public long MaxGapUs() { return maxGapUs; }
        public long MinGapUs() { return gapN == 0 ? 0 : minGapUs; }
        public long GapsOver11ms() { return gapsOver; }
        public long GapsUnder9ms() { return gapsUnder; }
        public long GapCount() { return gapN; }
        // signal: sine of the given amplitude (raw counts) on each axis plus an offset, at freq Hz
        public void SetSignal(double freq, double ax, double ay, double az, double ox, double oy, double oz)
        {
            freqHz = freq; ampX = ax; ampY = ay; ampZ = az; offX = ox; offY = oy; offZ = oz;
            frozen = false;
        }
        // unplug: the address stops answering.  plug: the part comes back as after a power-up
        // (asleep, registers at their reset values), so the firmware has to configure it again.
        public string Unplug()
        {
            if(!plugged) return "already unplugged";
            controller.Unregister(this);
            controller.Register(this, 0x69);       // nothing at 0x68 now, so the address is not acknowledged
            // the controller model keeps its current slave between transfers, so reset it as well.  the
            // firmware then sees the peripheral stop answering and recovers it the way it would on a bus fault
            controller.Reset();
            plugged = false;
            return "unplugged";
        }
        public void Plug()
        {
            if(plugged) return;
            Reset();
            controller.Unregister(this);
            controller.Register(this, 0x68);
            plugged = true;
        }
        // the next n sample reads return an all-zero triple, which the firmware treats as a failed read
        public void ZeroNext(int n) { zeroLeft = n; }
        // every nth sample read returns an all-zero triple (an intermittent fault)
        public void ZeroEvery(int n) { zeroEvery = n; }
        // runs of failures: of every 'every' reads the first 'run' fail.  run 2 defeats a single retry
        public void ZeroRun(int every, int run) { runEvery = every; runLen = run; }
        // each sample read fails with the given probability in per cent, from a fixed seed so a run repeats
        public void ZeroPercent(int percent, int seed) { zeroPercent = percent; rng = new Random(seed); }
        public void Freeze() { frozen = true; }
        public void Unfreeze() { frozen = false; }
        public void SetAllZero(bool on) { allZero = on; }
        public void SetWhoAmI(int value) { whoAmI = (byte)value; regs[0x75] = whoAmI; }
        public void ForceSleep() { regs[0x6B] |= 0x40; }
        public int  Pwr() { return regs[0x6B]; }
        public int  AccelRange() { return regs[0x1C]; }
        public long Reads() { return nReads; }
        public long Writes() { return writes; }

        private readonly byte[] regs = new byte[256];
        private readonly byte[] latched = new byte[6];
        private byte pointer;
        private byte whoAmI = 0x68;
        private long nReads;
        private long writes;
        private long sampleIndex;
        private readonly Antmicro.Renode.Peripherals.I2C.STM32F1_I2C controller;
        private readonly IMachine machine;
        private long lastReadUs = -1, maxGapUs, minGapUs = long.MaxValue, gapsOver, gapsUnder, gapN;
        private bool plugged = true;
        private int zeroLeft;
        private int zeroEvery;
        private int runEvery;
        private int runLen;
        private int zeroPercent;
        private Random rng = new Random(1);
        private bool frozen;
        private bool allZero;
        private short frozenX, frozenY, frozenZ;
        private double freqHz = 10.0, ampX = 0, ampY = 0, ampZ = 0, offX = 0, offY = 0, offZ = 16384;
    }

    // the monitor loses the name of a peripheral that is unplugged from the bus, so the plug and unplug calls
    // go through this always-present handle
    public class MpuCtl : IDoubleWordPeripheral
    {
        public MpuCtl(MpuSim target) { this.target = target; }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        public string Unplug() { return target.Unplug(); }
        public void Plug() { target.Plug(); }
        public void SetSignal(double freq, double ax, double ay, double az, double ox, double oy, double oz) { target.SetSignal(freq, ax, ay, az, ox, oy, oz); }
        public void Freeze() { target.Freeze(); }
        public void Unfreeze() { target.Unfreeze(); }
        public void SetAllZero(bool on) { target.SetAllZero(on); }
        public void SetWhoAmI(int value) { target.SetWhoAmI(value); }
        public void ForceSleep() { target.ForceSleep(); }
        public void ZeroNext(int n) { target.ZeroNext(n); }
        public void ZeroEvery(int n) { target.ZeroEvery(n); }
        public void ZeroRun(int every, int run) { target.ZeroRun(every, run); }
        public void ZeroPercent(int percent, int seed) { target.ZeroPercent(percent, seed); }
        public int  Pwr() { return target.Pwr(); }
        public int  AccelRange() { return target.AccelRange(); }
        public long Reads() { return target.Reads(); }
        public long Writes() { return target.Writes(); }
        public void ResetGaps() { target.ResetGaps(); }
        public long MaxGapUs() { return target.MaxGapUs(); }
        public long MinGapUs() { return target.MinGapUs(); }
        public long GapsOver11ms() { return target.GapsOver11ms(); }
        public long GapsUnder9ms() { return target.GapsUnder9ms(); }
        public long GapCount() { return target.GapCount(); }
        private readonly MpuSim target;
    }
}
