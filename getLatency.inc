;    Copyright 2014 Oeyvind Brandtsegg and Axel Tidemann
;
;    This file is part of [self.]
;
;    [self.] is free software: you can redistribute it and/or modify
;    it under the terms of the GNU General Public License version 3 
;    as published by the Free Software Foundation.
;
;    [self.] is distributed in the hope that it will be useful,
;    but WITHOUT ANY WARRANTY; without even the implied warranty of
;    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;    GNU General Public License for more details.
;
;    You should have received a copy of the GNU General Public License
;    along with [self.].  If not, see <http://www.gnu.org/licenses/>.


; measure roundtrip latency

	Smess1		= "Measure roundtrip latency, make sure you have sufficient bleed from speakers to microphone"
	Smess2		= "The audio output is recorded at the input and the latency measured"
	Smess3		= "If no latency measurements are printed, the signal was not sufficiently strong at the input"
                puts Smess1, 1
                puts Smess2, 1
                puts Smess3, 1

	ain		chnget "in1"
	kmetro		metro 1
	if kmetro > 0 then
	reinit testsig
	endif
	testsig:
	aenv		linseg 1, 0.1, 0, 1, 0
	rireturn
	;atest		mpulse 1, 1
	atest		rnd31 1, 1
	atest		= atest*aenv
			    chnset atest, "MasterOut1"
	kinrms		rms ain
	koutrms		rms atest
	kintrig		trigger kinrms, ampdbfs(-30), 0
	kouttrig	trigger koutrms, ampdbfs(-30), 0
	ktime		times
	kintime     init 0
	kouttime	init 0
	kintime		= (kintrig > 0 ? ktime : kintime)
	kouttime	= (kouttrig > 0 ? ktime : kouttime)
	kdiff 		= kintime-kouttime
	klatency	init 0
	klatency	= (kdiff > 0 ? kdiff : klatency)

	Slatency	sprintfk "roundtrip latency is %f seconds", klatency
                puts Slatency, klatency
                chnset klatency, "audio_io_latency"

                xtratim 1/kr
    krelease    release
    if krelease > 0 then
                dumpk  klatency, "roundtrip_latency.txt",8, 0
    endif
    
