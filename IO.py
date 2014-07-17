#!/usr/bin/python
# -*- coding: latin-1 -*-

import multiprocessing as mp

import cv2
import numpy as np
import zmq

from utils import send_array, recv_array
import myCsoundAudioOptions

# �MQ ports
CAMERA = 5561
PROJECTOR = 5562
MIC = 5563
SPEAKER = 5564
STATE = 5565
EXTERNAL = 5566
SNAPSHOT = 5567
EVENT = 5568

def video():
    me = mp.current_process()
    print me.name, 'PID', me.pid

    cv2.namedWindow('Output', cv2.WINDOW_NORMAL)
    video_feed = cv2.VideoCapture(0)
    frame_size = (160, 90)

    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind('tcp://*:{}'.format(CAMERA))

    subscriber = context.socket(zmq.PULL)
    subscriber.bind('tcp://*:{}'.format(PROJECTOR))
    
    while True:
        _, frame = video_feed.read()
        frame = cv2.resize(frame, frame_size)
        gray_image = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) / 255.

        send_array(publisher, np.ndarray.flatten(gray_image))
        
        try: 
            cv2.imshow('Output', 
                       cv2.resize(
                           np.resize(recv_array(subscriber, flags=zmq.DONTWAIT), (90,160)),
                           (640,360)))
        except:
            cv2.imshow('Output', np.random.rand(360, 640))

        cv2.waitKey(100)

def audio():
    me = mp.current_process()
    print me.name, 'PID', me.pid

    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind('tcp://*:{}'.format(MIC))

    subscriber = context.socket(zmq.PULL)
    subscriber.bind('tcp://*:{}'.format(SPEAKER))

    stateQ = context.socket(zmq.SUB)
    stateQ.connect('tcp://localhost:{}'.format(STATE))
    stateQ.setsockopt(zmq.SUBSCRIBE, b'') 

    eventQ = context.socket(zmq.SUB)
    eventQ.connect('tcp://localhost:{}'.format(EVENT))
    eventQ.setsockopt(zmq.SUBSCRIBE, b'') 

    snapshot = context.socket(zmq.REQ)
    snapshot.connect('tcp://localhost:{}'.format(SNAPSHOT))
    snapshot.send(b'Send me the state, please')
    state = snapshot.recv_json()

    poller = zmq.Poller()
    poller.register(subscriber, zmq.POLLIN)
    poller.register(stateQ, zmq.POLLIN)
    poller.register(eventQ, zmq.POLLIN)

    import csnd6
    cs = csnd6.Csound()
    arguments = csnd6.CsoundArgVList()
    arguments.Append("dummy")
    arguments.Append("self_dot.csd")
    csoundCommandline = myCsoundAudioOptions.myAudioDevices
    comlineParmsList = csoundCommandline.split(' ')
    for item in comlineParmsList:
        arguments.Append("%s"%item)
    cs.Compile(arguments.argc(), arguments.argv())
    stopflag = 0
    zeroChannelsOnNoBrain = 1
    
    fftsize = int(cs.GetChannel("fftsize"))
    ffttabsize = fftsize/2
    fftin_amptab = 1
    fftin_freqtab = 2
    fftout_amptab = 4
    fftout_freqtab = 5
    fftresyn_amptab = 7
    fftresyn_freqtab = 8
    
    # optimizations to avoid function lookup inside loop
    tGet = cs.TableGet 
    tSet = cs.TableSet
    cGet = cs.GetChannel
    cSet = cs.SetChannel
    perfKsmps = cs.PerformKsmps
    fftbinindices = range(ffttabsize)
    fftin_amptabs = [fftin_amptab]*ffttabsize
    fftin_freqtabs = [fftin_freqtab]*ffttabsize
    fftout_amptabs = [fftout_amptab]*ffttabsize
    fftout_freqtabs = [fftout_freqtab]*ffttabsize
    fftresyn_amptabs = [fftresyn_amptab]*ffttabsize
    fftresyn_freqtabs = [fftresyn_freqtab]*ffttabsize
    fftzeros = [0]*ffttabsize
    fftconst = [0.1]*ffttabsize
    fftin_amplist = [0]*ffttabsize
    fftin_freqlist = [0]*ffttabsize

    while not stopflag:
        stopflag = perfKsmps()
        fftinFlag = cGet("pvsinflag")
        fftoutFlag = cGet("pvsoutflag")
        
        if fftinFlag:
            fftin_amplist = map(tGet,fftin_amptabs,fftbinindices)
            fftin_freqlist = map(tGet,fftin_freqtabs,fftbinindices)
            #bogusamp = map(tSet,fftresyn_amptabs,fftbinindices,fftin_amplist)
            #bogusfreq = map(tSet,fftresyn_freqtabs,fftbinindices,fftin_freqlist)
        if fftoutFlag:
            fftout_amplist = map(tGet,fftout_amptabs,fftbinindices)
            fftout_freqlist = map(tGet,fftout_freqtabs,fftbinindices)

        events = dict(poller.poll(timeout=0))

        if stateQ in events:
            state = stateQ.recv_json()
        
        # get Csound channel data
        audioStatus = cGet("audioStatus")
        audioStatusTrig = cGet("audioStatusTrig")
        transient = cGet("transient")
        
        if state['autolearn']:
            if audioStatusTrig > 0:
                send('startrec', context)
            if audioStatusTrig < 0:
                send('stoprec', context)
                send('learn', context)

        if state['autorespond']:
            if audioStatusTrig > 0:
                send('startrec', context)
            if audioStatusTrig < 0:
                send('stoprec', context)
                send('respond', context) 

        if eventQ in events:
            pushbutton = eventQ.recv_json()
            if 'selfvoice' in pushbutton:
                mode = '{}'.format(pushbutton['selfvoice'])
                if mode in ['partikkel', 'spectral', 'noiseband']:
                    print 'self change voice to...', mode
                    cs.InputMessage('i -51 0 .1')
                    cs.InputMessage('i -52 0 .1')
                    cs.InputMessage('i -53 0 .1')
                    if mode == 'noiseband': cs.InputMessage('i 51 0 -1')
                    if mode == 'partikkel': cs.InputMessage('i 52 0 -1')
                    if mode == 'spectral': cs.InputMessage('i 53 0 -1')
                else:
                    print 'unknown voice mode', mode

            if 'inputLevel' in pushbutton:
                mode = '{}'.format(pushbutton['inputLevel'])
                if mode == 'mute': cs.InputMessage('i 21 0 .1 0')
                if mode == 'unmute': cs.InputMessage('i 21 0 .1 1')
                if mode == 'reset': 
                    cs.InputMessage('i 21 0 .1 0')
                    cs.InputMessage('i 21 1 .1 1')

            if 'calibrateAudio' in pushbutton:
                cs.InputMessage('i -17 0 1') # turn off old noise gate
                cs.InputMessage('i 12 0 4') # measure roundtrip latency
                cs.InputMessage('i 13 4 2') # get audio input noise print
                cs.InputMessage('i 14 6 -1 5') # enable noiseprint and self-output suppression
                cs.InputMessage('i 15 6.2 2') # get noise floor level 
                cs.InputMessage('i 16 8.3 0.1') # set noise gate shape
                cs.InputMessage('i 17 8.5 -1') # turn on new noise gate

            if 'csinstr' in pushbutton:
                # generic csound instr message
                cs.InputMessage('{}'.format(pushbutton['csinstr']))
                print 'sent {}'.format(pushbutton['csinstr'])

            if 'zerochannels' in pushbutton:
                zeroChannelsOnNoBrain = int('{}'.format(pushbutton['zerochannels']))

            if 'playfile' in pushbutton:
                print '[self.] wants to play {}'.format(pushbutton['playfile'])
                cs.InputMessage('i3 0 5 "%s"'%'{}'.format(pushbutton['playfile']))

        send_array(publisher, np.array([cGet("level1"), 
                                        cGet("pitch1ptrack"), 
                                        cGet("pitch1pll"), 
                                        cGet("autocorr1"), 
                                        cGet("centroid1"),
                                        cGet("spread1"), 
                                        cGet("skewness1"), 
                                        cGet("kurtosis1"), 
                                        cGet("flatness1"), 
                                        cGet("crest1"), 
                                        cGet("flux1"), 
                                        cGet("epochSig1"), 
                                        cGet("epochRms1"), 
                                        cGet("epochZCcps1")]))# + fftin_amplist + fftin_freqlist)) #FFT temporarily disabled

        if subscriber in events:
            sound = recv_array(subscriber)
            cSet("respondLevel1", sound[0])
            cSet("respondPitch1ptrack", sound[1])
            cSet("respondPitch1pll", sound[2])
            cSet("respondCentroid1", sound[4])
            # test partikkel generator
            cSet("partikkel1_amp", sound[0])
            cSet("partikkel1_grainrate", sound[1])
            cSet("partikkel1_wavfreq", sound[4])
            cSet("partikkel1_graindur", sound[3]+0.1)
            # transfer fft frame
            fft_index = 14
            #bogusamp = map(tSet,fftresyn_amptabs,fftbinindices,sound[fft_index:ffttabsize+fft_index]) #FFT temporarily disabled
            #bogusfreq = map(tSet,fftresyn_freqtabs,fftbinindices,sound[ffttabsize+fft_index:ffttabsize+fft_index+ffttabsize])

            '''
            # partikkel parameters ready to be set
            partikkelparmOffset = 5
            cSet("partikkel1_amp",sound[partikkelparmOffset+0])
            cSet("partikkel1_grainrate",sound[partikkelparmOffset+1])
            cSet("partikkel1_graindur",sound[partikkelparmOffset+2])
            cSet("partikkel1_sustain",sound[partikkelparmOffset+3])
            cSet("partikkel1_adratio",sound[partikkelparmOffset+4])
            cSet("partikkel1_wavfreq",sound[partikkelparmOffset+5])
            cSet("partikkel1_octaviation",sound[partikkelparmOffset+6])
            cSet("partikkel1_async_amount",sound[partikkelparmOffset+7])
            cSet("partikkel1_distribution",sound[partikkelparmOffset+8])
            cSet("partikkel1_randomask",sound[partikkelparmOffset+9])
            cSet("partikkel1_grFmFreq",sound[partikkelparmOffset+10])
            cSet("partikkel1_grFmIndex",sound[partikkelparmOffset+11])
            cSet("partikkel1_wavekey1",sound[partikkelparmOffset+12])
            cSet("partikkel1_wavekey2",sound[partikkelparmOffset+13])
            cSet("partikkel1_wavekey3",sound[partikkelparmOffset+14])
            cSet("partikkel1_wavekey4",sound[partikkelparmOffset+15])
            cSet("partikkel1_pitchFmFreq",sound[partikkelparmOffset+16])
            cSet("partikkel1_pitchFmIndex",sound[partikkelparmOffset+17])
            cSet("partikkel1_trainPartials",sound[partikkelparmOffset+18])
            cSet("partikkel1_trainChroma",sound[partikkelparmOffset+19])
            cSet("partikkel1_wavemorf",sound[partikkelparmOffset+20])
            '''
        else:
            if zeroChannelsOnNoBrain:  
                cSet("respondLevel1", 0)
                cSet("respondPitch1ptrack", 0)
                cSet("respondPitch1pll", 0)
                cSet("respondCentroid1", 0)
                # partikkel test
                cSet("partikkel1_amp", 0)
                cSet("partikkel1_grainrate", 0)
                cSet("partikkel1_wavfreq", 0)
                # zero fft frame 
                bogusamp = map(tSet,fftresyn_amptabs,fftbinindices,fftzeros)

# Setup so it can be accessed from processes which don't have a zmq context, i.e. for one-shot messaging
def send(message, context=None, host='localhost', port=EXTERNAL):
    context = context or zmq.Context()
    sender = context.socket(zmq.PUSH)
    sender.connect('tcp://{}:{}'.format(host, port))
    sender.send_json(message)
