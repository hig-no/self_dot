#!/usr/bin/python
# -*- coding: latin-1 -*-

#    Copyright 2014 Oeyvind Brandtsegg and Axel Tidemann
#
#    This file is part of [self.]
#
#    [self.] is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3 
#    as published by the Free Software Foundation.
#
#    [self.] is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with [self.].  If not, see <http://www.gnu.org/licenses/>.

''' [self.]

@author: Axel Tidemann, �yvind Brandtsegg
@contact: axel.tidemann@gmail.com, obrandts@gmail.com
@license: GPL
'''

import multiprocessing as mp
import os
import random
import utils
import time

import numpy as np
import zmq
from scipy.io import wavfile

from utils import send_array, recv_array
import myCsoundAudioOptions

VIDEO_SAMPLE_TIME = 100 # Milliseconds
NAP_STRIDE = 441
NAP_RATE = 22050

FRAME_SIZE = (640,480)
PROCESS_TIME_OUT = 5*60 
SYSTEM_TIME_OUT = 30*60 

# �MQ ports
CAMERA = 5561
PROJECTOR = 5562
MIC = 5563
SPEAKER = 5564
STATE = 5565
EXTERNAL = 5566 # If you change this, you're out of luck.
SNAPSHOT= 5567
EVENT = 5568
SCHEDULER = 5569
ROBO = 5570
COGNITION = 5571
FACE = 5572
BRAIN = 5573
ASSOCIATION = 5574
SENTINEL = 5575
LOGGER = 5576
DREAM = 5577
COUNTER = 5578

def video():
    import cv2

    cv2.namedWindow('Output', cv2.WND_PROP_FULLSCREEN)
    camera = cv2.VideoCapture(0)

    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind('tcp://*:{}'.format(CAMERA))

    projector = context.socket(zmq.PULL)
    projector.bind('tcp://*:{}'.format(PROJECTOR))
    
    eventQ = context.socket(zmq.SUB)
    eventQ.connect('tcp://localhost:{}'.format(EVENT))
    eventQ.setsockopt(zmq.SUBSCRIBE, b'')

    poller = zmq.Poller()
    poller.register(eventQ, zmq.POLLIN)
    poller.register(projector, zmq.POLLIN)

    while True:
        events = dict(poller.poll(timeout=0))

        if eventQ in events:
            pushbutton = eventQ.recv_json()
            if 'display2' in pushbutton:
                cv2.moveWindow('Output', 2000, 100)
            if 'fullscreen' in pushbutton:
                cv2.setWindowProperty('Output', cv2.WND_PROP_FULLSCREEN, cv2.cv.CV_WINDOW_FULLSCREEN)

        if projector in events:
            cv2.imshow('Output', cv2.resize(recv_array(projector), FRAME_SIZE))
        else:
            cv2.imshow('Output', np.zeros(FRAME_SIZE[::-1]))
        
        _, frame = camera.read()
        frame = cv2.resize(frame, FRAME_SIZE)
        send_array(publisher, frame)

        cv2.waitKey(VIDEO_SAMPLE_TIME)

def audio():
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind('tcp://*:{}'.format(MIC))

    robocontrol = context.socket(zmq.PUSH)
    robocontrol.connect('tcp://localhost:{}'.format(ROBO))

    subscriber = context.socket(zmq.PULL)
    subscriber.bind('tcp://*:{}'.format(SPEAKER))

    stateQ = context.socket(zmq.SUB)
    stateQ.connect('tcp://localhost:{}'.format(STATE))
    stateQ.setsockopt(zmq.SUBSCRIBE, b'') 

    eventQ = context.socket(zmq.SUB)
    eventQ.connect('tcp://localhost:{}'.format(EVENT))
    eventQ.setsockopt(zmq.SUBSCRIBE, b'') 

    sender = context.socket(zmq.PUSH)
    sender.connect('tcp://localhost:{}'.format(EXTERNAL))

    poller = zmq.Poller()
    poller.register(subscriber, zmq.POLLIN)
    poller.register(stateQ, zmq.POLLIN)
    poller.register(eventQ, zmq.POLLIN)

    memRecPath = myCsoundAudioOptions.memRecPath

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

    # optimizations to avoid function lookup inside loop
    tGet = cs.TableGet 
    tSet = cs.TableSet
    cGet = cs.GetChannel
    cSet = cs.SetChannel
    perfKsmps = cs.PerformKsmps

    filename = []
    counter = 0
    ampPitchCentroid = [[],[],[]]
    
    ambientFiles = [] # used by the ambient sound generator (instr 90 pp)
    ambientActive = 0
    prev_i_am_speaking = 0
    skip_file = 0
    recalibrate_timer_enable = True
    recalibrate_time = 120
    time_last_recorded = time.time()

    state = stateQ.recv_json()
    
    while not stopflag:
        counter += 1
        counter = counter%16000 # just to reset sometimes
        stopflag = cs.PerformKsmps()

        events = dict(poller.poll(timeout=0))

        if stateQ in events:
            state = stateQ.recv_json()

        # get Csound channel data
        audioStatus = cGet("audioStatus")           
        audioStatusTrig = cGet("audioStatusTrig")       # signals start of a statement (audio in)
        transient = cGet("transient")                   # signals start of a segment within a statement (audio in)        
        memRecTimeMarker = cGet("memRecTimeMarker")     # (in memRec) get (active record) the time since start of statement
        memRecSkiptime = cGet("memRecSkiptime")         # (in memRec) get the time (amount) of stripped sielence) in the latest segment
        memRecActive = cGet("memRecActive")             # flag to check if memoryRecording is currently recording to file in Csound
        memRecMaxAmp = cGet("memRecMaxAmp")             # max amplitude for each recorded file
        statusRel = cGet("statusRel")                   # audio status release time 
        noiseFloor = cGet("inputNoisefloor")            # measured noise floor in dB
        too_long_segment = cGet("too_long_segment")     # signals a segment that is longer thant we like
        too_long_sentence = cGet("too_long_sentence")     # signals a sentence that is longer thant we like
        
        i_am_speaking = cGet("i_am_speaking")           # signals cognition that I'm currently speaking
        cSet("i_am_speaking", 0)                        # reset channel, any playing voice instr will overwrite
        if i_am_speaking != prev_i_am_speaking:         # send if changed
            sender.send_json('i_am_speaking {}'.format(int(i_am_speaking)))
        prev_i_am_speaking = i_am_speaking
        
        panposition = cs.GetChannel("panalyzer_pan")
        in_amp = cs.GetChannel("followdb") #rather use envelope follower in dB than pure rms channel "in_amp")
        in_pitch = cs.GetChannel("in_pitch")
        in_centroid = cs.GetChannel("in_centroid")
        
        if state['roboActive'] > 0:
            if (panposition < 0.48) or (panposition > 0.52):
                print 'panposition', panposition
                robocontrol.send_json([1,'pan',panposition-.5])
            if (counter % 500) == 0:
                robocontrol.send_json([2,'pan',-1])
         
        if state['ambientSound'] > 0:
            if ambientActive == 0:
                cs.InputMessage('i 92 0 -1')
                ambientActive = 1
            if (counter % 4000) == 0:
                newtable, ambientFiles = utils.updateAmbientMemoryWavs(ambientFiles)
                cs.InputMessage('i 90 0 4 "%s"'%newtable)
        
        if state['ambientSound'] == 0:
            if ambientActive == 1:
                cs.InputMessage('i -92 0 1')
                ambientActive = 0
        
        if state['memoryRecording']:
            if audioStatusTrig > 0:
                skip_file = 0
                timestr = time.strftime('%Y_%m_%d_%H_%M_%S')
                print 'starting memoryRec', timestr
                tim_time = time.time()
                filename = memRecPath+timestr+'.wav'
                time_frac = tim_time-int(tim_time)
                instrNum = 34+time_frac
                cs.InputMessage('i %f 0 -1 "%s"'%(instrNum,filename))
                markerfileName = memRecPath+timestr+'.txt'
                markerfile = open(markerfileName, 'w')
                markerfile.write('Self. audio clip perceived at %s\n'%tim_time)
                segmentstring = 'Sub segments (start, skiptime, amp, pitch, cent): \n'
                segStart = 0.0
                ampPitchCentroid = [[],[],[]]
            if audioStatus > 0:
                ampPitchCentroid[0].append(in_amp)
                ampPitchCentroid[1].append(in_pitch)
                ampPitchCentroid[2].append(in_centroid)
            if (transient > 0) & (memRecActive > 0):
                if memRecTimeMarker == 0: pass
                else:
                    print '... ...get medians and update segments'
                    ampPitchCentroid[0].sort()
                    l = ampPitchCentroid[0]
                    ampMean = max(l)
                    ampPitchCentroid[1].sort()
                    l = ampPitchCentroid[1]
                    pitchMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.75)])
                    ampPitchCentroid[2].sort()
                    l = ampPitchCentroid[2]
                    centroidMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.9)])
                    ampPitchCentroid = [[],[],[]]
                    segmentstring += '%.3f %.3f %.3f %.3f %.3f\n'%(segStart,memRecSkiptime,ampMean,pitchMean,centroidMean)
                    segStart = memRecTimeMarker 
            if (audioStatusTrig < 0) & (memRecActive > 0):
                print '... ...get final medians and update segments'
                ampPitchCentroid[0].sort()
                l = ampPitchCentroid[0]
                ampMean = max(l)
                ampPitchCentroid[1].sort()
                l = ampPitchCentroid[1]
                pitchMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.75)])
                ampPitchCentroid[2].sort()
                l = ampPitchCentroid[2]
                centroidMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.9)])
                ampPitchCentroid = [[],[],[]]
                segmentstring += '%.3f %.3f %.3f %.3f %.3f\n'%(segStart,memRecSkiptime-statusRel,ampMean,pitchMean,centroidMean) #normal termination of recording, we should subtract statusRel from last skiptime
                #segmentstring += '%.3f %.3f %.3f %.3f %.3f\n'%(segStart,memRecSkiptime,ampMean,pitchMean,centroidMean) 
                segmentlist = segmentstring.split('\n')
                segmentlist.pop() # ditch the empty list item at the end
                markertablist = []
                markerTempTab = cGet("giMarkerTemp")
                for i in range(32):
                    markertime = tGet(int(markerTempTab), i)
                    markertablist.append(markertime)
                segmentstring = '{}\n'.format(segmentlist.pop(0))
                total_segment_time = 0.0
                skip_time = 0.0
                skip_count = 0
                skip_file = 0
                for i in range(len(segmentlist)):
                    segmentlist[i] = segmentlist[i].split(' ')
                print 'markertablist', markertablist
                print 'segmentlist',segmentlist
                
                for i in range(len(segmentlist)):
                    if markertablist[i] < 0 :
                        #print 'SKIPPING \n  SEGMENT \n    {}'.format(segmentlist[i])
                        skip_count += 1
                        if skip_count >= len(segmentlist): 
                            skip_file = 1
                            print 'SKIPPING EMPTY FILE at time {}'.format(timestr) 
                        if i<len(segmentlist)-1:
                            skip_time += float(segmentlist[i+1][0])-float(segmentlist[i][0])
                        else:
                            skip_time += memRecTimeMarker-float(segmentlist[i][0])
                    else:
                        segmentlist[i][0] = '%.3f'%total_segment_time
                        segment_n = ''
                        for item in segmentlist[i]: segment_n += str(item) + ' '
                        segment_n = segment_n.rstrip(' ')
                        segmentstring += segment_n+'\n'
                        if i<len(segmentlist)-1:
                            total_segment_time = float(segmentlist[i+1][0])-skip_time
                        else:
                            total_segment_time = memRecTimeMarker-skip_time
                #print 'segmentstring\n', segmentstring
                cs.InputMessage('i -%f 0 1'%instrNum)
                markerfile.write(segmentstring)
                markerfile.write('Total duration: %f\n'%total_segment_time)
                markerfile.write('\nMax amp for file: %f'%memRecMaxAmp)
                markerfile.close()
                print 'stopping memoryRec'            
            
            if too_long_segment > 0 or too_long_sentence > 0:
                for i in range(20):
                    print ' '*i, '*'*i
                if too_long_segment > 0:
                    print "TOO LONG SEGMENT"
                else:
                    print "TOO LONG SENTENCE"
                cs.InputMessage('i -%f 0 1'%instrNum)
                skip_file = 1
                cSet("too_long_segment", 0)
                cSet("too_long_sentence", 0)
                cSet("memRecActive", 0)
                memRecActive = 0
                sender.send_json('_audioLearningStatus 0')
                sender.send_json('stoprec')
                sender.send_json('calibrateAudio')
                
        if not state['memoryRecording'] and memRecActive:
            print '... ...turnoff rec, get final medians and update segments'
            ampPitchCentroid[0].sort()
            l = ampPitchCentroid[0]
            ampMean = max(l)
            ampPitchCentroid[1].sort()
            l = ampPitchCentroid[1]
            pitchMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.75)])
            ampPitchCentroid[2].sort()
            l = ampPitchCentroid[2]
            centroidMean = np.mean(l[int(len(l)*0.25):int(len(l)*0.9)])
            ampPitchCentroid = [[],[],[]]
            segmentstring += '%.3f %.3f %.3f %.3f %.3f\n'%(segStart,memRecSkiptime-statusRel,ampMean,pitchMean,centroidMean) #normal termination of recording, we should subtract statusRel from last skiptime
            #segmentstring += '%.3f %.3f %.3f %.3f %.3f\n'%(segStart,memRecSkiptime,ampMean,pitchMean,centroidMean) 
            segmentlist = segmentstring.split('\n')
            segmentlist.pop() # ditch the empty list item at the end
            markertablist = []
            for i in range(32):
                markertime = tGet(int(markerTempTab), i)
                markertablist.append(-1) #hard and dirty, skip all if we turn off memory recording while recording a sentence
            segmentstring = '{}\n'.format(segmentlist.pop(0))
            total_segment_time = 0.0
            skip_time = 0.0
            skip_count = 0
            skip_file = 0
            for i in range(len(segmentlist)):
                segmentlist[i] = segmentlist[i].split(' ')
            print 'markertablist', markertablist
            print 'segmentlist',segmentlist
            
            for i in range(len(segmentlist)):
                if markertablist[i] < 0 :
                    print 'SKIPPING \n  SEGMENT \n    {}'.format(segmentlist[i])
                    skip_count += 1
                    if skip_count >= len(segmentlist): 
                        skip_file = 1
                        print 'SKIPPING EMPTY FILE at time {}'.format(timestr) 
                    if i<len(segmentlist)-1:
                        skip_time += float(segmentlist[i+1][0])-float(segmentlist[i][0])
                    else:
                        skip_time += memRecTimeMarker-float(segmentlist[i][0])
                else:
                    segmentlist[i][0] = '%.3f'%total_segment_time
                    segment_n = ''
                    for item in segmentlist[i]: segment_n += str(item) + ' '
                    segment_n = segment_n.rstrip(' ')
                    segmentstring += segment_n+'\n'
                    if i<len(segmentlist)-1:
                        total_segment_time = float(segmentlist[i+1][0])-skip_time
                    else:
                        total_segment_time = memRecTimeMarker-skip_time
            print 'segmentstring\n', segmentstring
            cs.InputMessage('i -%f 0 1'%instrNum)
            markerfile.write(segmentstring)
            markerfile.write('Total duration: %f\n'%total_segment_time)
            markerfile.write('\nMax amp for file: %f'%memRecMaxAmp)
            markerfile.close()
            print 'stopping memoryRec'

        interaction = []
        
        if (state['autolearn'] or state['autorespond_single'] or state['autorespond_sentence']) and not skip_file:
            if audioStatusTrig > 0:
                sender.send_json('startrec')
                sender.send_json('_audioLearningStatus 1')
                time_last_recorded = time.time()
                recalibrate_timer_enable = True
            if audioStatusTrig < 0:
                sender.send_json('stoprec')
                sender.send_json('_audioLearningStatus 0')
                time_last_recorded = time.time()
                recalibrate_timer_enable = True
                if filename:
                    if state['autolearn']:
                        interaction.append('learnwav {}'.format(os.path.abspath(filename)))
                    if state['autorespond_single']:
                        interaction.append('respondwav_single {}'.format(os.path.abspath(filename)))
                    if state['autorespond_sentence']:
                        interaction.append('respondwav_sentence {}'.format(os.path.abspath(filename)))
        if (time.time()-time_last_recorded > recalibrate_time) and recalibrate_timer_enable:
            for i in range(20):
                print ' '*(20-i), '*'*(20-i)
            sender.send_json('calibrateAudio')
            recalibrate_timer_enable = False
                

        if interaction and not skip_file:
            sender.send_json('calculate_cochlear {}'.format(os.path.abspath(filename)))

            for command in interaction:
                sender.send_json(command)

        if eventQ in events:
            pushbutton = eventQ.recv_json()
            if 'selfvoice' in pushbutton:
                    print 'not implemented'

            if 'inputLevel' in pushbutton:
                mode = pushbutton['inputLevel']
                if mode == 'mute':
                    cs.InputMessage('i 21 0 .1 0')
                    print 'Mute'
                if mode == 'unmute':
                    cs.InputMessage('i 21 0 .1 1')
                    print 'Un-mute'
                if mode == 'reset': 
                    cs.InputMessage('i 21 0 .1 0')
                    cs.InputMessage('i 21 1 .1 1')

            if 'calibrateEq' in pushbutton:
                cs.InputMessage('i -99 0 1') # turn off master out
                cs.InputMessage('i 19 0.5 2') # eq profiling
                cs.InputMessage('i 99 3 -1') # turn on master out

            if 'setLatency' in pushbutton:
                value = pushbutton['setLatency']
                cSet("audio_io_latency",value) 
                print 'Csound roundtrip latency set to {}'.format(cGet("audio_io_latency"))

            if 'calibrateAudio' in pushbutton:
                cs.InputMessage('i -17 0 1') # turn off old noise gate
                cs.InputMessage('i 12 0 3.9') # measure roundtrip latency
                cs.InputMessage('i 13 4 1.9') # get audio input noise print
                cs.InputMessage('i 14 6 -1') # enable noiseprint and self-output suppression
                cs.InputMessage('i 15 6.2 2') # get noise floor level 
                cs.InputMessage('i 16 8.3 0.1') # set noise gate shape
                cs.InputMessage('i 17 8.5 -1') # turn on new noise gate
                                               
            if 'calibrateNoiseFloor' in pushbutton:
                cs.InputMessage('i -17 0 .1') # turn off old noise gate
                cs.InputMessage('i -14 0 .1') # turn off noiseprint and self-output suppression
                cs.InputMessage('i 13 .3 1.5') # get audio input noise print
                cs.InputMessage('i 14 2 -1') # enable noiseprint and self-output suppression
                cs.InputMessage('i 15 2.2 1.5') # get noise floor level 
                cs.InputMessage('i 16 3.9 0.1') # set noise gate shape
                cs.InputMessage('i 17 4 -1') # turn on new noise gate

            if 'csinstr' in pushbutton:
                # generic csound instr message
                cs.InputMessage('{}'.format(pushbutton['csinstr']))
                print 'sent {}'.format(pushbutton['csinstr'])

            if 'selfDucking' in pushbutton:
                value = pushbutton['selfDucking']
                cs.InputMessage('i 22 0 1 "selfDucking" %f'%float(value))

            if 'zerochannels' in pushbutton:
                zeroChannelsOnNoBrain = int('{}'.format(pushbutton['zerochannels']))

            if 'playfile' in pushbutton:
                #print '[self.] AUDIO playfile {}'.format(pushbutton['playfile'])
                try:
                    params = pushbutton['playfile']
                    voiceChannel, voiceType, start, soundfile, speed, segstart, segend, amp, maxamp = params.split(' ')
                    soundfile = str(soundfile)
                    voiceChannel = int(voiceChannel) # internal or external voice (primary/secondary associations)
                    instr = 60 + int(voiceType)
                    start = float(start)
                    segstart = float(segstart)
                    segend = float(segend)
                    amp = float(amp)
                    maxamp = float(maxamp)
                    speed = float(speed)
                    if voiceChannel == 2:
                        delaySend = -26 # delay send in dB
                        reverbSend = -23 # reverb send in dB
                    else:
                        delaySend = -96
                        reverbSend = -96 
                    csMessage = 'i %i %f 1 "%s" %f %f %f %f %i %f %f %f' %(instr, start, soundfile, segstart, segend, amp, maxamp, voiceChannel, delaySend, reverbSend, speed)
                    #print 'csMessage', csMessage                 
                    cs.InputMessage(csMessage)

                except Exception, e:
                    print e, 'Playfile aborted.'

