#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Given a DR spectrometer file, create one of more PSRFITS file(s).

$Rev$
$LastChangedBy$
$LastChangedDate$
"""

import os
import sys
import numpy
import ephem
import ctypes
import getopt

import psrfits_utils.psrfits_utils as pfu

from lsl.reader.ldp import DRSpecFile
from lsl.reader import errors
import lsl.astro as astro
import lsl.common.progress as progress
from lsl.statistics import robust, kurtosis

from _psr import *


def usage(exitCode=None):
    print """writePrsfits2FromDRSpec.py - Read in DR spectrometer files and create one or 
more PSRFITS file(s).

Usage: writePsrfits2FromDRSpec.py [OPTIONS] file

Options:
-h, --help                  Display this help information
-j, --skip                  Skip the specified number of seconds at the 
                            beginning of the file (default = 0)
-o, --output                Output file basename
-p, --no-sk-flagging        Disable on-the-fly SK flagging of RFI
-n, --no-summing            Do not sum polarizations for XX and YY files
-s, --source                Source name
-r, --ra                    Right Ascension (HH:MM:SS.SS, J2000)
-d, --dec                   Declination (sDD:MM:SS.S, J2000)
-4, --4bit-data             Save the spectra in 4-bit mode (default = 8-bit)

Note:  If a source name is provided and the RA or declination is not, the script
    will attempt to determine these values.
    
Note:  Stokes-mode data will disable summing
"""

    if exitCode is not None:
        sys.exit(exitCode)
    else:
        return True


def parseOptions(args):
    config = {}
    # Command line flags - default values
    config['offset'] = 0.0
    config['output'] = None
    config['args'] = []
    config['nsblk'] = 32
    config['useSK'] = True
    config['sumPols'] = True
    config['source'] = None
    config['ra'] = None
    config['dec'] = None
    config['dataBits'] = 8
    
    # Read in and process the command line flags
    try:
        opts, args = getopt.getopt(args, "hj:pns:o:r:d:4", ["help", "skip=", "no-sk-flagging", "no-summing", "source=", "output=", "ra=", "dec=", "4bit-mode"])
    except getopt.GetoptError, err:
        # Print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        usage(exitCode=2)
        
    # Work through opts
    for opt, value in opts:
        if opt in ('-h', '--help'):
            usage(exitCode=0)
        elif opt in ('-j', '--skip'):
            config['offset'] = float(value)
        elif opt in ('-p', '--no-sk-flagging'):
            config['useSK'] = False
        elif opt in ('-n', '--no-summing'):
            config['sumPols'] = False
        elif opt in ('-s', '--source'):
            config['source'] = value
        elif opt in ('-r', '--ra'):
            config['ra'] = value
        elif opt in ('-d', '--dec'):
            config['dec'] = value
        elif opt in ('-o', '--output'):
            config['output'] = value
        elif opt in ('-4', '--4bit-mode'):
            config['dataBits'] = 4
        else:
            assert False
            
    # Add in arguments
    config['args'] = args
    
    # Return configuration
    return config


def resolveTarget(name):
    import urllib
    
    try:
        result = urllib.urlopen('http://www3.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/NameResolver/find?target=%s' % urllib.quote_plus(name))
        
        line = result.readlines()
        target = (line[0].replace('\n', '').split('='))[1]
        service = (line[1].replace('\n', '').split('='))[1]
        service = service.replace('(', ' @ ')
        coordsys = (line[2].replace('\n', '').split('='))[1]
        ra = (line[3].replace('\n', '').split('='))[1]
        dec = (line[4].replace('\n', '').split('='))[1]
        
        temp = astro.deg_to_hms(float(ra))
        raS = "%i:%02i:%05.2f" % (temp.hours, temp.minutes, temp.seconds)
        temp = astro.deg_to_dms(float(dec))
        decS = "%+i:%02i:%04.1f" % ((-1.0 if temp.neg else 1.0)*temp.degrees, temp.minutes, temp.seconds)
        serviceS = service[0:-2]
        
    except (IOError, ValueError):
        raS = "---"
        decS = "---"
        serviceS = "Error"
        
    return raS, decS, serviceS


def main(args):
    # Parse command line options
    config = parseOptions(args)
    
    # Find out where the source is if needed
    if config['source'] is not None:
        if config['ra'] is None or config['dec'] is None:
            tempRA, tempDec, tempService = resolveTarget('PSR '+config['source'])
            print "%s resolved to %s, %s using '%s'" % (config['source'], tempRA, tempDec, tempService)
            out = raw_input('=> Accept? [Y/n] ')
            if out == 'n' or out == 'N':
                sys.exit()
            else:
                config['ra'] = tempRA
                config['dec'] = tempDec
                
    else:
        config['source'] = "None"
        
    if config['ra'] is None:
        config['ra'] = "00:00:00.00"
    if config['dec'] is None:
        config['dec'] = "+00:00:00.0"
        
    # Open
    idf = DRSpecFile(config['args'][0])
    nFramesFile = idf.getInfo('nFrames')
    LFFT = idf.getInfo('LFFT')
    
    # Load in basic information about the data
    srate = idf.getInfo('sampleRate')
    beam = idf.getInfo('beam')
    centralFreq1 = idf.getInfo('freq1')
    centralFreq2 = idf.getInfo('freq2')
    dataProducts = idf.getInfo('dataProducts')
    isLinear = ('XX' in dataProducts) or ('YY' in dataProducts)
    tInt = idf.getInfo('tInt')
    
    # Offset, if needed
    o = 0
    if config['offset'] != 0.0:
        o = idf.offset(config['offset'])
    nFramesFile -= int(round(o/tInt))
    
    # Sub-integration block size
    nsblk = config['nsblk']
    
    ## Date
    beginDate = ephem.Date(astro.unix_to_utcjd(idf.getInfo('tStart')) - astro.DJD_OFFSET)
    beginTime = beginDate.datetime()
    mjd = astro.jd_to_mjd(astro.unix_to_utcjd(idf.getInfo('tStart')))
    mjd_day = int(mjd)
    mjd_sec = (mjd-mjd_day)*86400
    if config['output'] is None:
        config['output'] = "drx_%05d_%s" % (mjd_day, config['source'].replace(' ', ''))
        
    # File summary
    print "Input Filename: %s" % config['args'][0]
    print "Date of First Frame: %s (MJD=%f)" % (str(beginDate),mjd)
    print "Beam: %i" % beam
    print "Tunings: %.1f Hz, %.1f Hz" % (centralFreq1, centralFreq2)
    print "Sample Rate: %i Hz" % srate
    print "Sample Time: %f s" % tInt
    print "Sub-block Time: %f s" % (tInt*nsblk,)
    print "Data Products: %s" % ','.join(dataProducts)
    print "Frames: %i (%.3f s)" % (nFramesFile, tInt*nFramesFile)
    print "---"
    print "Offset: %.3f s (%i frames)" % (o, o/tInt)
    print "---"
    
    # Create the output PSRFITS file(s)
    pfu_out = []
    if isLinear and config['sumPols']:
        polNames = 'I'
        nPols = 1
        def reduceEngine(x):
            y = numpy.zeros((2,x.shape[1]), dtype=numpy.float32)
            y[0,:] += x[0,:]
            y[0,:] += x[1,:]
            y[1,:] += x[2,:]
            y[1,:] += x[3,:]
            return y
    else:
        config['sumPols'] = False
        polNames = ''.join(dataProducts)
        nPols = len(dataProducts)
        reduceEngine = lambda x: x.astype(numpy.float32)
        
    if config['dataBits'] == 4:
        OptimizeDataLevels = OptimizeDataLevels4Bit
    else:
        OptimizeDataLevels = OptimizeDataLevels8Bit
        
    for t in xrange(1, 2+1):
        ## Basic structure and bounds
        pfo = pfu.psrfits()
        pfo.basefilename = "%s_b%it%i" % (config['output'], beam, t)
        pfo.filenum = 0
        pfo.tot_rows = pfo.N = pfo.T = pfo.status = pfo.multifile = 0
        pfo.rows_per_file = 32768
        
        ## Frequency, bandwidth, and channels
        if t == 1:
            pfo.hdr.fctr=centralFreq1/1e6
        else:
            pfo.hdr.fctr=centralFreq2/1e6
        pfo.hdr.BW = srate/1e6
        pfo.hdr.nchan = LFFT
        pfo.hdr.df = srate/1e6/LFFT
        pfo.hdr.dt = tInt
        
        ## Metadata about the observation/observatory/pulsar
        pfo.hdr.observer = "wP2FromDRSpec.py"
        pfo.hdr.source = config['source']
        pfo.hdr.fd_hand = 1
        pfo.hdr.nbits = config['dataBits']
        pfo.hdr.nsblk = nsblk
        pfo.hdr.ds_freq_fact = 1
        pfo.hdr.ds_time_fact = 1
        pfo.hdr.npol = nPols
        pfo.hdr.summed_polns = 1 if config['sumPols'] else 0
        pfo.hdr.obs_mode = "SEARCH"
        pfo.hdr.telescope = "LWA"
        pfo.hdr.frontend = "LWA"
        pfo.hdr.backend = "DRSpectrometer"
        pfo.hdr.project_id = "Pulsar"
        pfo.hdr.ra_str = config['ra']
        pfo.hdr.dec_str = config['dec']
        pfo.hdr.poln_type = "LIN"
        pfo.hdr.poln_order = polNames
        pfo.hdr.date_obs = str(beginTime.strftime("%Y-%m-%dT%H:%M:%S"))     
        pfo.hdr.MJD_epoch = pfu.get_ld(mjd)
        
        ## Setup the subintegration structure
        pfo.sub.tsubint = pfo.hdr.dt*pfo.hdr.nsblk
        pfo.sub.bytes_per_subint = pfo.hdr.nchan*pfo.hdr.npol*pfo.hdr.nsblk*pfo.hdr.nbits/8
        pfo.sub.dat_freqs   = pfu.malloc_doublep(pfo.hdr.nchan*8)				# 8-bytes per double @ LFFT channels
        pfo.sub.dat_weights = pfu.malloc_floatp(pfo.hdr.nchan*4)				# 4-bytes per float @ LFFT channels
        pfo.sub.dat_offsets = pfu.malloc_floatp(pfo.hdr.nchan*pfo.hdr.npol*4)		# 4-bytes per float @ LFFT channels per pol.
        pfo.sub.dat_scales  = pfu.malloc_floatp(pfo.hdr.nchan*pfo.hdr.npol*4)		# 4-bytes per float @ LFFT channels per pol.
        if config['dataBits'] == 4:
            pfo.sub.data = pfu.malloc_ucharp(pfo.hdr.nchan*pfo.hdr.npol*pfo.hdr.nsblk)	# 1-byte per unsigned char @ (LFFT channels x pols. x nsblk sub-integrations) samples
            pfo.sub.rawdata = pfu.malloc_ucharp(pfo.hdr.nchan*pfo.hdr.npol*pfo.hdr.nsblk/2)	# 4-bits per nibble @ (LFFT channels x pols. x nsblk sub-integrations) samples
        else:
            pfo.sub.rawdata = pfu.malloc_ucharp(pfo.hdr.nchan*pfo.hdr.npol*pfo.hdr.nsblk)	# 1-byte per unsigned char @ (LFFT channels x pols. x nsblk sub-integrations) samples
            
        ## Create and save it for later use
        pfu.psrfits_create(pfo)
        pfu_out.append(pfo)
        
    freqBaseMHz = numpy.fft.fftshift( numpy.fft.fftfreq(LFFT, d=1.0/srate) ) / 1e6
    for i in xrange(len(pfu_out)):
        # Define the frequencies available in the file (in MHz)
        pfu.convert2_double_array(pfu_out[i].sub.dat_freqs, freqBaseMHz + pfu_out[i].hdr.fctr, LFFT)
        
        # Define which part of the spectra are good (1) or bad (0).  All channels
        # are good except for the two outermost.
        pfu.convert2_float_array(pfu_out[i].sub.dat_weights, numpy.ones(LFFT),  LFFT)
        pfu.set_float_value(pfu_out[i].sub.dat_weights, 0,      0)
        pfu.set_float_value(pfu_out[i].sub.dat_weights, LFFT-1, 0)
        
        # Define the data scaling (default is a scale of one and an offset of zero)
        pfu.convert2_float_array(pfu_out[i].sub.dat_offsets, numpy.zeros(LFFT*nPols), LFFT*nPols)
        pfu.convert2_float_array(pfu_out[i].sub.dat_scales,  numpy.ones(LFFT*nPols),  LFFT*nPols)
        
    # Speed things along, the data need to be processed in units of 'nsblk'.  
    # Find out how many frames that corresponds to.
    chunkSize = nsblk
    chunkTime = tInt*nsblk
    
    # Calculate the SK limites for weighting
    if config['useSK'] and isLinear:
        skN = int(tInt*srate / LFFT)
        skLimits = kurtosis.getLimits(4.0, M=1.0*nsblk, N=1.0*skN)
        
        GenerateMask = lambda x: ComputePseudoSKMask(x, LFFT, skN, skLimits[0], skLimits[1])
    else:
        def GenerateMask(x):
            flag = numpy.ones((4, LFFT), dtype=numpy.float32)
            flag[:,0] = 0.0
            flag[:,-1] = 0.0
            return flag
            
    # Create the progress bar so that we can keep up with the conversion.
    try:
        pbar = progress.ProgressBarPlus(max=nFramesFile/chunkSize, span=55)
    except AttributeError:
        pbar = progress.ProgressBar(max=nFramesFile/chunkSize, span=55)
        
    # Go!
    done = False
    
    siCount = 0
    while True:
        ## Read in the data
        try:
            readT, t, data = idf.read(chunkTime)
            siCount += 1
        except errors.eofError:
            break
            
        ## FFT (really promote and reshape since the data are already spectra)
        spectra = data.astype(numpy.float64)
        spectra = spectra.reshape(spectra.shape[0], -1)
        
        ## S-K flagging
        flag = GenerateMask(spectra)
        weight1 = numpy.where( flag[:2,:].sum(axis=0) == 0, 0, 1 ).astype(numpy.float32)
        weight2 = numpy.where( flag[2:,:].sum(axis=0) == 0, 0, 1 ).astype(numpy.float32)
        ff1 = 1.0*(LFFT - weight1.sum()) / LFFT
        ff2 = 1.0*(LFFT - weight2.sum()) / LFFT
        
        ## Detect power
        data = reduceEngine(spectra)
        
        ## Optimal data scaling
        bzero, bscale, bdata = OptimizeDataLevels(data, LFFT)
        
        ## Polarization mangling
        bzero1 = bzero[:nPols,:].T.ravel()
        bzero2 = bzero[nPols:,:].T.ravel()
        bscale1 = bscale[:nPols,:].T.ravel()
        bscale2 = bscale[nPols:,:].T.ravel()
        bdata1 = bdata[:nPols,:].T.ravel()
        bdata2 = bdata[nPols:,:].T.ravel()
        
        ## Write the spectra to the PSRFITS files
        for j,sp,bz,bs,wt in zip(range(2), (bdata1, bdata2), (bzero1, bzero2), (bscale1, bscale2), (weight1, weight2)):
            ## Time
            pfu_out[j].sub.offs = (pfu_out[j].tot_rows)*pfu_out[j].hdr.nsblk*pfu_out[j].hdr.dt+pfu_out[j].hdr.nsblk*pfu_out[j].hdr.dt/2.0
            
            ## Data
            ptr, junk = sp.__array_interface__['data']
            if config['dataBits'] == 4:
                ctypes.memmove(int(pfu_out[j].sub.data), ptr, pfu_out[j].hdr.nchan*nPols*pfu_out[j].hdr.nsblk)
            else:
                ctypes.memmove(int(pfu_out[j].sub.rawdata), ptr, pfu_out[j].hdr.nchan*nPols*pfu_out[j].hdr.nsblk)
                
            ## Zero point
            ptr, junk = bz.__array_interface__['data']
            ctypes.memmove(int(pfu_out[j].sub.dat_offsets), ptr, pfu_out[j].hdr.nchan*nPols*4)
            
            ## Scale factor
            ptr, junk = bs.__array_interface__['data']
            ctypes.memmove(int(pfu_out[j].sub.dat_scales), ptr, pfu_out[j].hdr.nchan*nPols*4)
            
            ## SK
            ptr, junk = wt.__array_interface__['data']
            ctypes.memmove(int(pfu_out[j].sub.dat_weights), ptr, pfu_out[j].hdr.nchan*4)
            
            ## Save
            pfu.psrfits_write_subint(pfu_out[j])
            
        ## Update the progress bar and remaining time estimate
        pbar.inc()
        sys.stdout.write('%5.1f%% %5.1f%% %s\r' % (ff1*100, ff2*100, pbar.show()))
        sys.stdout.flush()
        
    # Update the progress bar with the total time used
    sys.stdout.write('              %s\n' % pbar.show())
    sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
    
