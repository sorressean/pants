###############################################################################
#
# Copyright 2011 Chris Davis
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################

###############################################################################
# Imports
###############################################################################

import errno
import select

from pants.shared import log

#: Detect which system calls are available.
_use_epoll, _use_kqueue = False, False
if hasattr(select, "epoll"):
    _use_epoll = True
elif hasattr(select, "kqueue"):
    _use_kqueue = True


###############################################################################
# Reactor Class
###############################################################################

class Reactor(object):
    """
    The reactor class.
    
    A reactor is an object that manages network channels and maintains
    consistent network activity on those channels' sockets.
    """
    #: Socket events - these correspond to epoll() states.
    NONE = 0x00
    READ = 0x01
    WRITE = 0x04
    ERROR = 0x08 | 0x10 | 0x2000
    
    def __init__(self, poll=None):
        """
        Initialises the reactor.
        
        Parameters:
            poll - The polling object to be used by the reactor. This
                defaults to _EPoll on Linux 2.6+, _KQueue on BSD and
                _Select on all other operating systems.
        """
        if poll:
            self._poll = poll
        elif _use_epoll:
            self._poll = _EPoll()
        elif _use_kqueue:
            self._poll = _KQueue()
        else:
            self._poll = _Select()
        
        self._channels = {}
    
    ##### Channel Methods ###################################################
    
    def add_channel(self, channel):
        """
        Adds a channel to the reactor.
        
        Parameters:
            channel - A channel object.
        """
        self._channels[channel.fileno] = channel
        self._poll.add(channel.fileno, channel.events)
    
    def modify_channel(self, channel):
        """
        Modifies a channel's state.
        
        Parameters:
            channel - A channel object.
        """
        self._poll.modify(channel.fileno, channel.events)
    
    def remove_channel(self, channel):
        """
        Removes a channel from the reactor.
        
        Parameters:
            channel - A channel object.
        """
        self._channels.pop(channel.fileno, None)
        
        try:
            self._poll.remove(channel.fileno)
        except (IOError, OSError):
            log.exception("Error while removing channel %d." % channel.fileno)
    
    ##### Control Methods #####################################################
    
    def poll(self, timeout=0.02):
        """
        Polls the reactor.
        
        Identifies active sockets, then reads from, writes to and raises
        exceptions on those sockets.
        """
        try:
            events = self._poll.poll(timeout)
        except Exception, err: # TODO Is it Exception or select.error?
            if err[0] == errno.EINTR:
                log.warning("Interrupted system call.", exc_info=True)
                return
            else:
                raise
        
        for fileno, events in events.items():
            try:
                self._channels[fileno]._handle_events(events)
            except (IOError, OSError), err:
                if err[0] == errno.EPIPE:
                    # EPIPE: Broken pipe.
                    self._channels[fileno].close_immediately()
                else:
                    log.exception("Error while handling I/O events on channel %d." % fileno)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                log.exception("Error while handling I/O events on channel %d." % fileno)


###############################################################################
# _EPoll Class
###############################################################################

class _EPoll(object):
    """
    An epoll()-based polling object.
    """
    def __init__(self):
        """
        Initialises the _EPoll object.
        """
        self._epoll = select.epoll()
    
    def add(self, fileno, events):
        """
        Adds a socket to the polling object.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        self._epoll.register(fileno, events)
    
    def modify(self, fileno, events):
        """
        Modifies a registered socket's state.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        self._epoll.modify(fileno, events)
    
    def remove(self, fileno):
        """
        Removes a socket from the polling object.
        
        Parameters:
            fileno - The socket's file number.
        """
        self._epoll.unregister(fileno)
    
    def poll(self, timeout):
        """
        Uses the epoll() system call to identify active sockets.
        
        epoll() can only be used on Linux 2.6+
        """
        epoll_events = self._epoll.poll(timeout)
        events = {}
        
        for fileno, event in epoll_events:
            if event & select.EPOLLIN:
                events[fileno] = events.get(fileno, 0) | Reactor.READ
            if event & select.EPOLLOUT:
                events[fileno] = events.get(fileno, 0) | Reactor.WRITE
            if event & (select.EPOLLERR | select.EPOLLHUP | 0x2000):
                events[fileno] = events.get(fileno, 0) | Reactor.ERROR
        
        return events


###############################################################################
# _KQueue Class
###############################################################################

class _KQueue(object):
    """
    A kqueue()-based polling object.
    """
    def __init__(self):
        """
        Initialises the _KQueue object.
        """
        self._kqueue = select.kqueue()
    
    def add(self, fileno, events):
        """
        Adds a socket to the polling object.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        self._control(fileno, events, select.KQ_EV_ADD)
    
    def modify(self, fileno, events):
        """
        Modifies a registered socket's state.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        self.remove(fileno)
        self.add(fileno, events)
    
    def remove(self, fileno):
        """
        Removes a socket from the polling object.
        
        Parameters:
            fileno - The socket's file number.
        """
        self._control(fileno, events, select.KQ_EV_DELETE)
    
    def poll(self, timeout):
        """
        Uses the kqueue() system call to identify active sockets.
        
        kqueue() can only be used on BSD
        """
        kqueue_events = self._kqueue.control(None, 1024, timeout)
        events = {}
        
        for event in kqueue_events:
            fileno = event.ident
            
            if event.filter == select.KQ_FILTER_READ:
                events[fileno] = events.get(fileno, 0) | Reactor.READ
            if event.filter == select.KQ_FILTER_WRITE:
                events[fileno] = events.get(fileno, 0) | Reactor.WRITE
            if event.flags & select.KQ_EV_ERROR:
                events[fileno] = events.get(fileno, 0) | Reactor.ERROR
        
        return events
    
    def _control(self, fileno, events, flags):
        kqueue_events = []
        
        if events & Reactor.WRITE:
            event = select.kevent(fileno, filter=select.KQ_FILTER_WRITE,
                                  flags=flags)
            kqueue_events.append(event)
        
        if events & Reactor.READ or not kqueue_events:
            event = select.kevent(fileno, filter=select.KQ_FILTER_READ,
                                  flags=flags)
            kqueue_events.append(event)
        
        for event in kqueue_events:
            self._kqueue.control([event], 0)


###############################################################################
# _Select Class
###############################################################################

class _Select(object):
    """
    A select()-based polling object.
    """
    def __init__(self):
        """
        Initialises the _Select object.
        """
        self._r = set()
        self._w = set()
        self._e = set()
    
    def add(self, fileno, events):
        """
        Adds a socket to the polling object.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        if events & Reactor.READ:
            self._r.add(fileno)
        if events & Reactor.WRITE:
            self._w.add(fileno)
        if events & Reactor.ERROR:
            self._e.add(fileno)
    
    def modify(self, fileno, events):
        """
        Modifies a registered socket's state.
        
        Parameters:
            fileno - The socket's file number.
            events - The events the socket is listening for.
        """
        self.remove(fileno)
        self.add(fileno, events)
    
    def remove(self, fileno):
        """
        Removes a socket from the polling object.
        
        Parameters:
            fileno - The socket's file number.
        """
        self._r.discard(fileno)
        self._w.discard(fileno)
        self._e.discard(fileno)
    
    def poll(self, timeout):
        """
        Uses the select() system call to identify active sockets.
        
        select()'s performance is relatively poor. On Windows, it is
        limited to 512 file descriptors.
        """
        r, w, e, = select.select(self._r, self._w, self._e, timeout)
        
        events = {}
        
        for fileno in r:
            events[fileno] = events.get(fileno, 0) | Reactor.READ
        for fileno in w:
            events[fileno] = events.get(fileno, 0) | Reactor.WRITE
        for fileno in e:
            events[fileno] = events.get(fileno, 0) | Reactor.ERROR
        
        return events


###############################################################################
# Initialisation
###############################################################################

reactor = Reactor()