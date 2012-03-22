#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Given a DRX file, plot the time averaged spectra for each beam output."""

import os
import sys
import math
import numpy
import ephem
import getopt
import psrfits_utils.psrfits_utils as pfu

import lsl.reader.drx as drx
import lsl.reader.errors as errors
import lsl.correlator.fx as fxc
import lsl.astro as astro

def usage(exitCode=None):
	print """drxSpectra.py - Read in DRX files and create a collection of 
time-averaged spectra.

Usage: drxSpectra.py [OPTIONS] file

Options:
-h, --help                  Display this help information
-l, --fft-length            Set FFT length (default = 4096)
-o, --output                Output file basename
-s, --sum                   Sum the 2 polarizations for a particular beam/tune
--ra                        Right Ascension
--dec                       Declination
"""

	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseOptions(args):
	config = {}
	# Command line flags - default values
	config['LFFT'] = 4096
	config['output'] = None
        config['window'] = fxc.noWindow
        config['verbose'] = True
	config['args'] = []
        config['sumpolarizations'] = True
        config['ra'] = "00:00:00.0"
        config['dec'] = "00:00:00.0"

	# Read in and process the command line flags
	try:
	  opts, args = getopt.getopt(args, "hs:lo", ["help", "sum","fft-length=", "output=","ra=","dec="])
        except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
	
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		elif opt in ('-l', '--fft-length'):
			config['LFFT'] = int(value)
                elif opt in ('--ra'):
                        config['ra'] = value
                elif opt in ('--dec'):
                        config['dec'] = value
                elif opt in ('-s', '--sum'):
                        config['sumpolarizations'] = True
		elif opt in ('-o', '--output'):
			config['output'] = value
		else:
			assert False
	
	# Add in arguments
	config['args'] = args

	# Return configuration
	return config


def bestFreqUnits(freq):
	"""Given a numpy array of frequencies in Hz, return a new array with the
	frequencies in the best units possible (kHz, MHz, etc.)."""

	# Figure out how large the data are
	scale = int(math.log10(freq.max()))
	if scale >= 9:
		divis = 1e9
		units = 'GHz'
	elif scale >= 6:
		divis = 1e6
		units = 'MHz'
	elif scale >= 3:
		divis = 1e3
		units = 'kHz'
	else:
		divis = 1
		units = 'Hz'

	# Convert the frequency
	newFreq = freq / divis

	# Return units and freq
	return (newFreq, units)


def main(args):
	# Parse command line options
	config = parseOptions(args)

	# Length of the FFT
	LFFT = config['LFFT']

	fh = open(config['args'][0], "rb")
	nFramesFile = os.path.getsize(config['args'][0]) / drx.FrameSize
        print "FrameSize=%d" % drx.FrameSize
	junkFrame = drx.readFrame(fh)
	
	fh.seek(0)
	srate = junkFrame.getSampleRate()
	beams = drx.getBeamCount(fh)
	tunepols = drx.getFramesPerObs(fh)
	tunepol = tunepols[0] + tunepols[1] + tunepols[2] + tunepols[3]
	skippedsome=0
        count=0
        while tunepol<4:
          junkFrame = drx.readFrame(fh)
          tunepols = drx.getFramesPerObs(fh)
          tunepol = tunepols[0] + tunepols[1] + tunepols[2] + tunepols[3]
          if skippedsome==0:
            print "Some frames do not have both tunings, skipping ahead..."
          skippedsome=1
#          print "%f" % junkFrame.getTime()
          count+=1
        
        junkFrame = drx.readFrame(fh)
        beam1,tune1,pol1 = junkFrame.parseID()
	print "Beam/Tune/Pols: %i %i %i" % (beam1,tune1,pol1)
        tune=tune1
        while tune==tune1:
          junkFrame = drx.readFrame(fh)
          beam,tune,pol = junkFrame.parseID()
          count+=1
        junkFrame = drx.readFrame(fh)
        beam,tune,pol = junkFrame.parseID()
	print "Beam/Tune/Pols: %i %i %i %f" % (beam,tune,pol,junkFrame.getTime())
        count+=1
        junkFrame = drx.readFrame(fh)
        beam,tune,pol = junkFrame.parseID()
	print "Beam/Tune/Pols: %i %i %i %f" % (beam,tune,pol,junkFrame.getTime())
#        junkFrame = drx.readFrame(fh)
#        beam,tune,pol = junkFrame.parseID()
#	print "Beam/Tune/Pols: %i %i %i %f" % (beam,tune,pol,junkFrame.getTime())
#        junkFrame = drx.readFrame(fh)
#        beam,tune,pol = junkFrame.parseID()
#	print "Beam/Tune/Pols: %i %i %i %f" % (beam,tune,pol,junkFrame.getTime())
#        junkFrame = drx.readFrame(fh)
#        beam,tune,pol = junkFrame.parseID()
#	print "Beam/Tune/Pols: %i %i %i %f" % (beam,tune,pol,junkFrame.getTime())
#        sys.exit(0)
        if skippedsome==1:
          print "Skipped %d frames" % count
          nFramesFile = (os.path.getsize(config['args'][0])-drx.FrameSize*count) / drx.FrameSize
        beampols = tunepol
        framespertunpol = nFramesFile/beampols
        jumpnumframes=0
        numout=0
        sumpolarizations=config['sumpolarizations']
        numframesatatime=4096
        nchan = 4096
        nsblk = 4096
        
	# Date
	beginDate = ephem.Date(astro.unix_to_utcjd(junkFrame.getTime()) - astro.DJD_OFFSET)
        mjd = astro.jd_to_mjd(astro.unix_to_utcjd(junkFrame.getTime()))
        mjd_day = int(mjd)
        mjd_sec = (mjd-mjd_day)*86400
        prefix = "drx_%05d_%05d" % (mjd_day,int(mjd_sec))

#        sys.exit(0)
        if skippedsome==1:
          print "Skipped %d frames" % count
          nFramesFile = (os.path.getsize(config['args'][0])-drx.FrameSize*count) / drx.FrameSize
        beampols = tunepol
        framespertunpol = nFramesFile/beampols
        jumpnumframes=0
        numout=0
        sumpolarizations=config['sumpolarizations']
        numframesatatime=4096
        nchan = 4096
        nsblk = 4096
        
	# Date
	beginDate = ephem.Date(astro.unix_to_utcjd(junkFrame.getTime()) - astro.DJD_OFFSET)
        mjd = astro.jd_to_mjd(astro.unix_to_utcjd(junkFrame.getTime()))
        mjd_day = int(mjd)
        mjd_sec = (mjd-mjd_day)*86400
        prefix = "drx_%05d_%05d" % (mjd_day,int(mjd_sec))

	# File summary
	print "Input Filename: %s" % config['args'][0]
	print "Date of First Frame: %s %f" % (str(beginDate),mjd)
	print "Beams: %i" % beams
	print "Tune/Pols: %i %i %i %i" % tunepols
        print "beampols: %i" % beampols
	print "Sample Rate: %i Hz" % srate
	print "Sample Time: %f s" % (4096.0/srate)
        if numout==0:
          numout=nFramesFile
        print "Frames: %i (%.3f s)" % (numout, 1.0 * numout * 4096 / srate / beampols)
        print "Number of frames/tune/pol: %d " % (framespertunpol)
	print "---"
        mjd=mjd+(jumpnumframes * 4096 / srate / beampols) / 86400
        print "mjd=%f" % mjd
        pfu_out = []
	# Master loop over all of the file chunks
	masterCount = {}
	standMapper = []
        pfu_points = []
        subintdata = numpy.zeros((beampols,nchan*nsblk))
        firstpass = []
#	masterWeight = numpy.zeros((nChunks, beampols, LFFT-1))
#	masterSpectra = numpy.zeros((nChunks, beampols, LFFT-1))

#        data = numpy.zeros((beampols,4096/beampols), dtype=numpy.csingle)
        allzeros=numpy.zeros(4096)
        allones=numpy.ones(4096)
        data1 = numpy.zeros((beampols,numframesatatime,4096),dtype=numpy.csingle)
        kk=0
        for i in range(framespertunpol):
            sys.stdout.write("%d/%d\r" % (i,framespertunpol))
            if i>=jumpnumframes and i<jumpnumframes+numout:
              for j in range(beampols):
                if skippedsome==1 and i==0 and j==0:
                  cFrame = junkFrame
                else:
                  cFrame = drx.readFrame(fh, Verbose=False)
	        beam,tune,pol = cFrame.parseID()
                aStand = 4*(beam-1) + 2*(tune-1) + pol
           
                if aStand not in standMapper:
                  standMapper.append(aStand)
                  oStand = 1*aStand
                  aStand = standMapper.index(aStand)
                  print "Mapping beam %i, tune. %1i, pol. %1i (%2i) to array index %3i" % (beam, tune, pol, oStand, aStand)
                  if sumpolarizations == True:
                    fileprefix = "%s_b%dt%d" % (prefix,beam,tune)
                  else:
                    fileprefix = "%s_b%dt%dp%d" % (prefix,beam,tune,pol)
                  pfo = pfu.psrfits()
                  pfo.basefilename = fileprefix
                  pfo.filenum = 0
                  pfo.tot_rows = pfo.N = pfo.T = pfo.status = pfo.multifile = 0;
                  pfo.rows_per_file=4096;
                  pfo.hdr.df = srate/1000000.0/4096.0
                  print pfo.hdr.df
                  try:
                    centralfreq=cFrame.getCentralFreq()
                  except AttributeError:
                    from lsl.common.dp import fS
                    centralfreq=fS * ((cFrame.data.flags>>32) & (2**32-1))/2**32
                  pfo.hdr.fctr=centralfreq/1000000
                  pfo.hdr.BW = srate/1000000
                  pfo.hdr.nchan = nchan
                  pfo.hdr.nbits = 8
                  pfo.hdr.nsblk = nsblk
                  pfo.hdr.dt = (4096/srate)
                  pfo.hdr.ds_freq_fact=1
                  pfo.hdr.ds_time_fact=1
                  if sumpolarizations == True:
                    pfo.hdr.npol=1
                    pfo.hdr.summed_polns=1
                  else:
                    pfo.hdr.npol=1
                    pfo.hdr.summed_polns=0
                  pfo.hdr.obs_mode="SEARCH"
                  pfo.hdr.telescope="LWA"
                  pfo.hdr.ra_str=config['ra']
                  pfo.hdr.dec_str=config['dec']
                  pfo.hdr.MJD_epoch=pfu.get_ld(mjd);
                  if sumpolarizations == True:
                    pfo.sub.bytes_per_subint=pfo.hdr.nchan*pfo.hdr.nsblk*pfo.hdr.nbits/8
                  else:
                    pfo.sub.bytes_per_subint=pfo.hdr.nchan*pfo.hdr.nsblk*pfo.hdr.nbits/8*pfo.hdr.npol
                  pfo.sub.dat_freqs=pfu.malloc_floatp(4096*4)
                  pfo.sub.dat_weights=pfu.malloc_floatp(4096*4)
                  pfo.sub.dat_offsets=pfu.malloc_floatp(4096*4)
                  pfo.sub.dat_scales=pfu.malloc_floatp(4096*4)
                  pfo.sub.rawdata=pfu.malloc_ucharp(pfo.hdr.nchan*pfo.hdr.nsblk)
                  if sumpolarizations == False or j%2 == 0:
                    pfu.psrfits_create(pfo)
                  pfu_out.append(pfo)
                  pfu_points.append(0)
                  subdata = numpy.zeros(pfo.hdr.nsblk*pfo.hdr.nchan)
#                  subintdata.append(subdata)
                  firstpass.append(True)
                else:
                  aStand = standMapper.index(aStand)
	        data1[j,kk,0:4096] = cFrame.data.iq
                if kk==numframesatatime-1:
	          freq, tempSpec = fxc.SpecMaster(data1[j], LFFT=LFFT, window=config['window'], verbose=config['verbose'], SampleRate=srate, CentralFreq=(pfu_out[aStand].hdr.fctr*1000000))
                  if firstpass[aStand] == True:
                    if sumpolarizations == False or j%2 == 0:
                      for freqchan in range(0,4095):
                        if freqchan==0:
                          freq[freqchan]=pfu_out[aStand].hdr.fctr-pfu_out[aStand].hdr.BW/2.0+pfu_out[aStand].hdr.df
#                        freq[freqchan]=numpy.float32(freq[freqchan]/1000000)
                        else:
                          freq[freqchan]=freq[freqchan-1]+pfu_out[aStand].hdr.df
#                        freq[freqchan]=(freqchan+1)*pfu_out[aStand].hdr.df+pfu_out[aStand].hdr.fctr-pfu_out[aStand].hdr.BW/2.0
                      pfu.convert2_float_array(pfu_out[aStand].sub.dat_freqs,freq,4096)
                      pfu.set_float_value(pfu_out[aStand].sub.dat_freqs,4095,freq[4094]+freq[4094]-freq[4093])
                      pfu.convert2_float_array(pfu_out[aStand].sub.dat_weights,allones,4096)
                      pfu.set_float_value(pfu_out[aStand].sub.dat_weights,4095,0)
                      pfu.convert2_float_array(pfu_out[aStand].sub.dat_offsets,allzeros,4096)
                      pfu.convert2_float_array(pfu_out[aStand].sub.dat_scales,allones,4096)
                      firstpass[aStand]=False
                  for k in range(0,numframesatatime):
                    pfu_points[aStand]+=1
                    subintdata[aStand][(pfu_points[aStand]%pfo.hdr.nsblk)*4096:(pfu_points[aStand]%pfo.hdr.nsblk)*4096+4095]=tempSpec[k][0:4095]
                  if sumpolarizations == True:
                    if j%2 == 0:
                      continue
                    else:
                      subintdata[aStand-1]=subintdata[aStand-1]+subintdata[aStand]
                      if (i%pfo.hdr.nsblk==pfo.hdr.nsblk-1):
                        pfu_out[aStand-1].sub.offs=(pfu_out[aStand-1].tot_rows)*pfo.hdr.nsblk*pfo.hdr.dt
                        pfu.convert_uchar_array(pfu_out[aStand-1].sub.rawdata,subintdata[aStand-1],pfo.hdr.nchan*pfo.hdr.nsblk)
                        pfu.psrfits_write_subint(pfu_out[aStand-1])
                      
                  else:  
                    if (i%pfo.hdr.nsblk==pfo.hdr.nsblk-1):
                      pfu_out[aStand].sub.offs=(pfu_out[aStand].tot_rows)*pfo.hdr.nsblk*pfo.hdr.dt
                      pfu.convert_uchar_array(pfu_out[aStand].sub.rawdata,subintdata[aStand],pfo.hdr.nchan*pfo.hdr.nsblk)
                      pfu.psrfits_write_subint(pfu_out[aStand])
              kk=kk+1
              if kk%numframesatatime==0:
                kk=0
        sys.exit(0)

if __name__ == "__main__":
	main(sys.argv[1:])
